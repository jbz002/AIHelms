-- model_rewrite.lua — openresty 网关 body.model 改写
--
-- 职责：定时从后端拉取 (model_id -> has_anthropic/has_openai) 映射缓存到内存；
--       请求阶段按 (端点, 映射) 决定是否把裸名改写为 裸名(Anthropic) 后缀组。
--
-- 改写规则（与后端 (Anthropic) 拆组语义对齐）：
--   /v1/messages  + has_anthropic        -> 裸名(Anthropic)（anthropic 凭证原生 passthrough）
--   /v1/messages  + 仅 openai            -> 不改（litellm 自然 403，提示模型不支持 anthropic 入口）
--   /v1/chat/completions + 仅 anthropic  -> 裸名(Anthropic)（litellm 翻译）
--   /v1/chat/completions + has_openai    -> 不改（openai 凭证原生）
--   其他端点                          -> 不改

local _M = {}

local cjson = require "cjson.safe"
local SUFFIX = "(Anthropic)"
local REFRESH_INTERVAL = 30  -- 秒

-- 映射缓存：model_id -> { has_anthropic=bool, has_openai=bool }
local map = {}


-- cosocket 手写 HTTP GET（openresty:alpine 不带 lua-resty-http，timer 内用 cosocket）
-- 解析主机名到 IP：优先 /etc/hosts（extra_hosts 注入的 host.docker.internal），
-- 找不到回退原名（走 nginx resolver，用于生产容器名 aihelms）
local function resolve_host(name)
    if name:match("^%d+%.%d+%.%d+%.%d+$") then return name end
    local f = io.open("/etc/hosts", "r")
    if not f then return name end
    local found
    for line in f:lines() do
        local ip = line:match("^(%d+%.%d+%.%d+%.%d+)%s")
        if ip and line:find(name, 1, true) then found = ip; break end
    end
    f:close()
    return found or name
end

local function fetch_map(premature)
    if premature then return end
    local host = os.getenv("BACKEND_HOST")
    if not host or host == "" then
        ngx.log(ngx.ERR, "C1: BACKEND_HOST env not set")
        return
    end
    local target = resolve_host(host)
    local sock = ngx.socket.tcp()
    sock:settimeout(5000)
    local ok, err = sock:connect(target, 8000)
    if not ok then
        ngx.log(ngx.WARN, "C1: connect backend " .. host .. " failed: " .. tostring(err))
        return
    end
    local req = "GET /api/v1/internal/model-anthropic-map HTTP/1.0\r\nHost: "
        .. host .. "\r\nConnection: close\r\n\r\n"
    sock:send(req)
    local full, rerr = sock:receive("*a")
    sock:close()
    if not full then
        ngx.log(ngx.WARN, "C1: recv backend failed: " .. tostring(rerr))
        return
    end
    local sep = full:find("\r\n\r\n", 1, true)
    if not sep then return end
    local body = cjson.decode(full:sub(sep + 4))
    if not body or not body.data or not body.data.models then
        ngx.log(ngx.WARN, "C1: model map invalid response")
        return
    end
    local new_map = {}
    for _, mi in ipairs(body.data.models) do
        new_map[mi.model_id] = {
            has_anthropic = mi.has_anthropic == true,
            has_openai = mi.has_openai == true,
        }
    end
    map = new_map
    ngx.log(ngx.WARN, "C1: model map refreshed, " .. #body.data.models .. " models")
end


function _M.start_timer()
    -- 启动即拉一次（timer.at 0），并起定时刷新
    local ok, err = ngx.timer.at(0, fetch_map)
    if not ok then
        ngx.log(ngx.ERR, "C1: initial timer failed: " .. tostring(err))
    end
    local ok2, err2 = ngx.timer.every(REFRESH_INTERVAL, fetch_map)
    if not ok2 then
        ngx.log(ngx.ERR, "C1: periodic timer failed: " .. tostring(err2))
    end
end


local function ends_with(s, suffix)
    return #s >= #suffix and s:sub(-#suffix) == suffix
end


function _M.rewrite()
    if ngx.var.request_method ~= "POST" then return end
    local uri = ngx.var.uri
    local is_messages = (uri == "/v1/messages")
    local is_chat = (uri == "/v1/chat/completions")
    if not (is_messages or is_chat) then return end

    ngx.req.read_body()
    local raw = ngx.req.get_body_data()
    if not raw then return end
    local data = cjson.decode(raw)
    if not data or type(data.model) ~= "string" then return end

    local orig = data.model
    -- 已带后缀（用户/admin 直填组名）或裸名不在映射表，不改
    if ends_with(orig, SUFFIX) then return end
    local info = map[orig]
    if not info then return end

    local new_model = orig
    if is_messages then
        if info.has_anthropic then
            new_model = orig .. SUFFIX
        end
        -- 纯 openai：不改，让 litellm 自然 403
    elseif is_chat then
        if not info.has_openai and info.has_anthropic then
            new_model = orig .. SUFFIX
        end
        -- 有 openai：走裸名原生；均无：不改让 litellm 处理
    end

    if new_model ~= orig then
        data.model = new_model
        ngx.req.set_body_data(cjson.encode(data))
        ngx.log(ngx.WARN, "C1REWRITE uri=" .. uri .. " orig=" .. orig .. " new=" .. new_model)
    end
end


return _M
