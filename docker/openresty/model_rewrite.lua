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

-- 映射缓存：model_id -> { has_anthropic=bool, has_openai=bool, supports_vision=bool }
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
    -- BACKEND_PORT: prod=aihelms 监听端口(30720), dev 默认 8000
    local bport = tonumber(os.getenv("BACKEND_PORT") or "8000")
    local ok, err = sock:connect(target, bport)
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
            supports_vision = mi.supports_vision == true,
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


-- 剥掉请求 messages 里的 image block（非视觉模型不支持图片输入）。
-- 兼容两种方言：OpenAI 的 {type="image_url"} 与 Anthropic 的 {type="image"}。
-- 剥后 content 数组若为空，补一个占位 text，避免空 content 被上游拒绝。
-- 返回是否发生了改动。
local function strip_images(data)
    local messages = data.messages
    if type(messages) ~= "table" then return false end
    local changed = false
    for _, msg in ipairs(messages) do
        local content = msg.content
        if type(content) == "table" then
            local kept = {}
            for _, block in ipairs(content) do
                local bt = type(block) == "table" and block.type or nil
                if bt == "image_url" or bt == "image" then
                    changed = true
                else
                    kept[#kept + 1] = block
                end
            end
            if #kept == 0 then
                kept = { { type = "text", text = "[image removed]" } }
            end
            msg.content = kept
        end
    end
    return changed
end


-- GET /v1/models 响应过滤:剔除 id 以 (Anthropic) 结尾的条目
-- 网关已把裸名自动路由到正确后缀组,客户端不应看到这些方言分身
function _M.filter_models_body()
    local chunk = ngx.arg[1]
    local eof = ngx.arg[2]
    if chunk and #chunk > 0 then
        ngx.ctx.models_buf = (ngx.ctx.models_buf or "") .. chunk
    end
    if not eof then
        ngx.arg[1] = nil
        return
    end
    local body = ngx.ctx.models_buf or ""
    ngx.ctx.models_buf = nil
    local data = cjson.decode(body)
    if data and type(data.data) == "table" then
        local kept = {}
        for _, mi in ipairs(data.data) do
            if type(mi.id) == "string" and not ends_with(mi.id, SUFFIX) then
                kept[#kept + 1] = mi
            end
        end
        data.data = kept
        ngx.arg[1] = cjson.encode(data)
    else
        ngx.arg[1] = body
    end
end

-- 响应体被改写,长度变化,清 Content-Length 走 chunked
function _M.strip_content_length()
    ngx.header.content_length = nil
end


function _M.rewrite()
    if ngx.var.request_method ~= "POST" then return end
    local uri = ngx.var.uri
    local is_messages = (uri == "/v1/messages")
    local is_chat = (uri == "/v1/chat/completions")
    if not (is_messages or is_chat) then return end

    ngx.req.read_body()
    local raw = ngx.req.get_body_data()
    -- 兜底：body 超过 client_body_buffer_size 落盘临时文件时 get_body_data 为 nil，
    -- 必须读文件，否则大请求改写静默失效、走错方言组
    if not raw then
        local body_file = ngx.req.get_body_file()
        if not body_file then return end
        local f = io.open(body_file, "rb")
        if not f then return end
        raw = f:read("*a")
        f:close()
    end
    if not raw or raw == "" then return end
    local data = cjson.decode(raw)
    if not data or type(data.model) ~= "string" then return end

    local orig = data.model
    local info = map[orig]
    -- 带后缀的组名（用户直填）剥后缀查 map，拿 supports_vision 决定是否剥图
    if not info and ends_with(orig, SUFFIX) then
        info = map[orig:sub(1, -#SUFFIX - 1)]
    end

    local changed = false
    if info then
        -- ① model 方言改写（仅裸名，带后缀不改）
        if not ends_with(orig, SUFFIX) then
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
                changed = true
            end
        end
        -- ② 非视觉模型剥 image block
        if not info.supports_vision and strip_images(data) then
            changed = true
        end
    end

    if changed then
        ngx.req.set_body_data(cjson.encode(data))
        ngx.log(ngx.WARN, "C1REWRITE uri=" .. uri .. " orig=" .. orig)
    end
end


return _M
