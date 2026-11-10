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
--   /v1/responses + 仅 anthropic         -> 裸名(Anthropic)（litellm responses→anthropic 桥接，
--                                           2026-10-26 dev 实测 v1.103 对 anthropic 前缀部署 200）
--   /v1/responses + has_openai           -> 不改（litellm 原生 responses 转发）
--   /v1/messages/count_tokens            -> 与 messages 同规则（anthropic 部署加后缀）
--   /v1/responses/compact                -> 与 responses 同规则
--   模型名 [1m] 标记                     -> 一律剥离（Claude Code 的 1M 上下文标记）
--   文本模型（supports_vision=false）    -> 剥 image/document/file/input_audio 等媒体块
--   其他端点                          -> 不改

local _M = {}

local cjson = require "cjson.safe"
-- lua-cjson decode 后空数组与空对象同表示（均为空 table），re-encode 会把
-- 客户端的 "tools":[] 变成 {} 破坏请求结构（2026-08-25 生产事故）。
-- array_mt（cjson 2.1+）给空 table 打数组标记，encode 时还原为 []。
local cjson_strict = require "cjson"
local ARRAY_MT = cjson_strict.array_mt or cjson_strict.empty_array
local SUFFIX = "(Anthropic)"
-- Claude Code 开启 1M 上下文时会往模型名追加 [1m]；平台模型名不含该标记，
-- 必须在查映射/转发前剥掉，否则整条链路 404。
local ONE_M_CONTEXT_MARKER = "[1m]"
local REFRESH_INTERVAL = 30  -- 秒

-- 映射缓存：model_id -> { has_anthropic, has_openai, supports_vision, inject={能力字段集} }
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
    -- BACKEND_PORT: prod=aihelms 监听端口(30720), dev 默认 8100（8000 已被 ai-assistant backend 占用）
    local bport = tonumber(os.getenv("BACKEND_PORT") or "8100")
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
        -- inject: /v1/models 响应注入字段（OpenAI 标准无能力字段，litellm 不吐，平台侧补）
        local inject = {
            supports_vision = mi.supports_vision == true,
            supports_function_calling = mi.supports_function_calling == true,
            supports_reasoning = mi.supports_reasoning == true,
            supports_response_schema = mi.supports_response_schema == true,
            supports_parallel_function_calling =
                mi.supports_parallel_function_calling == true,
            supports_tool_choice = mi.supports_tool_choice == true,
        }
        if mi.mode then inject.mode = mi.mode end
        new_map[mi.model_id] = {
            has_anthropic = mi.has_anthropic == true,
            has_openai = mi.has_openai == true,
            supports_vision = mi.supports_vision == true,
            inject = inject,
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


local function escape_pattern(s)
    return (s:gsub("([%^%$%(%)%%%.%[%]%*%+%-%?])", "%%%1"))
end


-- lua-cjson 把 "tools":[] 与 {} 都 decode 成空 table，re-encode 时一律变 {}。
-- 对「raw JSON 里是空数组、decode 后是空 table」的顶层字段打数组标记，encode 还原 []。
-- 仅在 body 需要改写重编码时调用（未改写的 body 原样透传，无此风险）。
local function mark_empty_arrays(data, raw)
    if not ARRAY_MT then return end
    for k, v in pairs(data) do
        if type(v) == "table" and next(v) == nil then
            if raw:find('"' .. escape_pattern(k) .. '"%s*:%s*%[%s*%]') then
                setmetatable(v, ARRAY_MT)
            end
        end
    end
end


-- 剥掉 content block 数组里的非文本媒体块（文本模型不支持时）。
-- 覆盖 Anthropic(image/document)、OpenAI(image_url/audio/file) 与
-- Responses(input_image/input_file/input_audio) 的块类型；
-- tool_result 与嵌套 content 递归处理；全部剥空时补占位 text，避免上游拒绝空 content。
local MEDIA_BLOCK_TYPES = {
    image = true,
    image_url = true,
    input_image = true,
    document = true,
    file = true,
    input_file = true,
    input_audio = true,
    audio = true,
}

local function strip_media_from_blocks(blocks)
    local kept = {}
    local changed = false
    for _, block in ipairs(blocks) do
        local bt = type(block) == "table" and block.type or nil
        if bt and MEDIA_BLOCK_TYPES[bt] then
            changed = true
        else
            if type(block) == "table" and type(block.content) == "table" then
                local inner, inner_changed = strip_media_from_blocks(block.content)
                if inner_changed then
                    block.content = inner
                    changed = true
                end
            end
            kept[#kept + 1] = block
        end
    end
    if changed and #kept == 0 then
        kept = { { type = "text", text = "[media removed]" } }
    end
    return kept, changed
end


-- 剥掉请求 messages 里的媒体 block（顶层 content 数组 + tool_result 内层）。
-- 返回是否发生了改动。
local function strip_media(data)
    local messages = data.messages
    if type(messages) ~= "table" then return false end
    local changed = false
    for _, msg in ipairs(messages) do
        local content = msg.content
        if type(content) == "table" then
            local kept, msg_changed = strip_media_from_blocks(content)
            if msg_changed then
                msg.content = kept
                changed = true
            end
        end
    end
    return changed
end


-- /v1/responses 的输入不在 messages 而是一组 input 条目；条目本身可能是媒体块，
-- 也可能是 message 条目、内部再嵌 content 数组。
local function strip_media_from_responses(data)
    local input = data.input
    if type(input) ~= "table" then return false end
    local kept = {}
    local changed = false
    for _, item in ipairs(input) do
        local item_type = type(item) == "table" and item.type or nil
        if item_type and MEDIA_BLOCK_TYPES[item_type] then
            changed = true
        else
            if type(item) == "table" and type(item.content) == "table" then
                local inner, inner_changed = strip_media_from_blocks(item.content)
                if inner_changed then
                    item.content = inner
                    changed = true
                end
            end
            kept[#kept + 1] = item
        end
    end
    if changed then
        data.input = kept
    end
    return changed
end


-- GET /v1/models 响应处理:剔除 id 以 (Anthropic) 结尾的方言分身条目,
-- 并给每条模型对象注入平台能力字段(supports_* 全集 + mode)。
-- 网关已把裸名自动路由到正确后缀组,客户端不应看到分身;
-- OpenAI 标准模型对象无能力字段、litellm 不吐,由平台侧(source of truth)补
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
                local info = map[mi.id]
                if info and info.inject then
                    for k, v in pairs(info.inject) do
                        mi[k] = v
                    end
                end
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
    -- count_tokens 与 messages 同方言（body.model 同样需要按 anthropic 部署改写）
    local is_messages = (uri == "/v1/messages"
        or uri == "/v1/messages/count_tokens")
    -- /v1/responses（Codex 等客户端）与 chat 同规则；compact 与 responses 同族
    local is_chat = (uri == "/v1/chat/completions" or uri == "/v1/responses"
        or uri == "/v1/responses/compact")
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
    -- [1m] 是 Claude Code 的客户端标记，不属于平台模型名
    local lookup = orig
    if ends_with(lookup, ONE_M_CONTEXT_MARKER) then
        lookup = lookup:sub(1, -#ONE_M_CONTEXT_MARKER - 1)
    end
    local info = map[lookup]
    -- 带后缀的组名（用户直填）剥后缀查 map，拿 supports_vision 决定是否剥媒体
    if not info and ends_with(lookup, SUFFIX) then
        info = map[lookup:sub(1, -#SUFFIX - 1)]
    end

    local changed = false
    local media_changed = false
    -- [1m] 与方言映射无关：未知模型也要剥，否则上游 404
    if lookup ~= orig then
        data.model = lookup
        changed = true
    end
    if info then
        -- ① model 方言改写（仅裸名，带后缀不改；lookup 已剥 [1m]）
        if not ends_with(lookup, SUFFIX) then
            local new_model = lookup
            if is_messages then
                if info.has_anthropic then
                    new_model = lookup .. SUFFIX
                end
                -- 纯 openai：不改，让 litellm 自然 403
            elseif is_chat then
                if not info.has_openai and info.has_anthropic then
                    new_model = lookup .. SUFFIX
                end
                -- 有 openai：走裸名原生；均无：不改让 litellm 处理
            end
            if new_model ~= orig then
                data.model = new_model
                changed = true
            end
        end
        -- ② 文本模型剥非文本媒体块（image/document/file/audio，含嵌套内容）
        if not info.supports_vision then
            if strip_media(data) then media_changed = true end
            if strip_media_from_responses(data) then media_changed = true end
            if media_changed then changed = true end
        end
    end

    local forward_body = raw
    if changed then
        mark_empty_arrays(data, raw)
        forward_body = cjson.encode(data)
        ngx.req.set_body_data(forward_body)
        ngx.log(
            ngx.WARN,
            "C1REWRITE uri=" .. uri .. " orig=" .. orig
                .. " new=" .. tostring(data.model)
                .. " media=" .. tostring(media_changed)
        )
    end
    -- 供 @rectify_retry 复用（error_page 内部跳转后请求可能已消费 body buffer）
    ngx.ctx.al_forward_body = forward_body
end


local SWITCH_HINT =
    "（AIHelms 提示：该错误常见于切换模型或供应商后——历史会话中的思考签名/加密推理状态由原模型签发，"
    .. "新模型无法验证。请新开会话后重试。）"


local function lower_contains(haystack, needle)
    return string.find(haystack, needle, 1, true) ~= nil
end


-- 与 cc-switch thinking_rectifier / opaque_state_rectifier 的触发条件对齐。
-- 错误提示只负责把上游英文报错补充成用户可执行的提示；请求整流见下方
-- retry_with_rectified_body（由 nginx error_page 触发，整流后重试一次）。
local function is_switch_related_error(lower)
    if lower_contains(lower, "invalid signature") then return true end
    if lower_contains(lower, "must start with a thinking block") then return true end
    if lower_contains(lower, "redacted_thinking") then return true end
    if lower_contains(lower, "encrypted_content")
        or lower_contains(lower, "encrypted content") then
        return true
    end
    if lower_contains(lower, "could not decrypt")
        or lower_contains(lower, "failed to decrypt")
        or lower_contains(lower, "decryption failed")
        or lower_contains(lower, "invalid encrypted") then
        return true
    end
    if lower_contains(lower, "thought signature")
        and (lower_contains(lower, "not valid") or lower_contains(lower, "invalid")) then
        return true
    end
    if lower_contains(lower, "signature") and lower_contains(lower, "thinking") then
        return true
    end
    return false
end


local function append_hint(value)
    if type(value) ~= "string" or value == "" then return false, value end
    local lower = string.lower(value)
    if lower_contains(lower, "aihelms 提示") then return false, value end
    if not is_switch_related_error(lower) then return false, value end
    return true, value .. SWITCH_HINT
end


-- 就地改写错误对象里的 message（兼容 OpenAI / Anthropic / LiteLLM 三种封套）。
local function annotate_error_data(data)
    if type(data) ~= "table" then return false end
    local err = data.error
    if type(err) == "table" then
        local changed, value = append_hint(err.message)
        if changed then
            err.message = value
            return true
        end
    elseif type(err) == "string" then
        local changed, value = append_hint(err)
        if changed then
            data.error = value
            return true
        end
    end
    for _, key in ipairs({ "message", "detail" }) do
        local changed, value = append_hint(data[key])
        if changed then
            data[key] = value
            return true
        end
    end
    return false
end


-- 纯函数：输入原始 JSON 字符串，命中切换模型类错误时返回追加提示后的 JSON，
-- 否则返回 nil（调用方原样透传）。
function _M.annotate_error_body(raw)
    if type(raw) ~= "string" or raw == "" then return nil end
    local data = cjson.decode(raw)
    if not data or not annotate_error_data(data) then return nil end
    mark_empty_arrays(data, raw)
    local ok, encoded = pcall(cjson.encode, data)
    if not ok or not encoded then return nil end
    return encoded
end


-- header_filter: 仅对 JSON 错误响应开启缓冲并清掉 Content-Length（body 可能变长）
function _M.prepare_error_hint()
    if ngx.status < 400 then return end
    local ct = ngx.header["Content-Type"]
    if type(ct) == "table" then ct = ct[1] end
    if not ct or not lower_contains(string.lower(tostring(ct)), "json") then return end
    ngx.ctx.al_error_buffer = ""
    ngx.header.content_length = nil
end


-- body_filter: 缓冲错误体，EOF 时尝试追加提示后输出
function _M.annotate_switch_error()
    local buf = ngx.ctx.al_error_buffer
    if buf == nil then return end
    local chunk = ngx.arg[1]
    if chunk and #chunk > 0 then
        ngx.ctx.al_error_buffer = buf .. chunk
    end
    if not ngx.arg[2] then
        ngx.arg[1] = nil
        return
    end
    local body = ngx.ctx.al_error_buffer or ""
    ngx.ctx.al_error_buffer = nil
    local annotated = _M.annotate_error_body(body)
    if annotated then
        ngx.log(ngx.WARN, "C1HINT annotated model-switch error, bytes=" .. #annotated)
        ngx.arg[1] = annotated
    else
        ngx.arg[1] = body
    end
end


-- ==== 自动整流：切换模型/供应商后重试一次 ====
-- 触发链：location 匹配三个聊天端点 → proxy_intercept_errors + error_page 400 422
--        → @rectify_retry → retry_with_rectified_body()。
-- 规则对齐 cc-switch thinking_rectifier / opaque_state_rectifier 的最小侵入子集：
--   /v1/messages         去 thinking/redacted_thinking 块与残留 signature；
--                        顶层 thinking=enabled 且末条 assistant 含 tool_use 时去掉顶层 thinking
--   /v1/chat/completions 去 reasoning_content / reasoning 字段
--   /v1/responses        去 reasoning / compaction 条目、去 encrypted_content 片段与字段
-- 只重试一次；整流后仍失败返回第二次结果，错误提示过滤器照常追加提示。
-- 整体开关：openresty 进程环境变量 RECTIFY_ENABLED=0 可关闭（无需改代码）。

local RECTIFY_ENABLED = os.getenv("RECTIFY_ENABLED") ~= "0"


local function sanitize_anthropic(data)
    local changed = false
    local messages = data.messages
    if type(messages) == "table" then
        for _, msg in ipairs(messages) do
            local content = type(msg) == "table" and msg.content or nil
            if type(content) == "table" then
                local kept = {}
                for _, block in ipairs(content) do
                    local bt = type(block) == "table" and block.type or nil
                    if bt == "thinking" or bt == "redacted_thinking" then
                        changed = true
                    else
                        if type(block) == "table" and block.signature ~= nil then
                            block.signature = nil
                            changed = true
                        end
                        kept[#kept + 1] = block
                    end
                end
                if #kept ~= #content then
                    if #kept == 0 then
                        kept = { { type = "text", text = "[thinking removed]" } }
                    end
                    msg.content = kept
                end
            end
        end
    end

    -- 与 cc-switch 对齐：thinking 开启但末条 assistant 已不以 thinking 开头且含 tool_use 时，
    -- 上游会报 "must start with a thinking block"；此时移除顶层 thinking 配置。
    if type(data.thinking) == "table" and data.thinking.type == "enabled" then
        local last_assistant
        if type(messages) == "table" then
            for i = #messages, 1, -1 do
                local msg = messages[i]
                if type(msg) == "table" and msg.role == "assistant" then
                    last_assistant = msg
                    break
                end
            end
        end
        local content = last_assistant and last_assistant.content
        if type(content) == "table" and #content > 0 then
            local first_type = type(content[1]) == "table" and content[1].type or nil
            local has_tool_use = false
            for _, block in ipairs(content) do
                if type(block) == "table" and block.type == "tool_use" then
                    has_tool_use = true
                    break
                end
            end
            if first_type ~= "thinking" and first_type ~= "redacted_thinking"
                and has_tool_use then
                data.thinking = nil
                changed = true
            end
        end
    end
    return changed
end


local function sanitize_chat(data)
    local changed = false
    local messages = data.messages
    if type(messages) == "table" then
        for _, msg in ipairs(messages) do
            if type(msg) == "table" then
                if msg.reasoning_content ~= nil then
                    msg.reasoning_content = nil
                    changed = true
                end
                if msg.reasoning ~= nil then
                    msg.reasoning = nil
                    changed = true
                end
            end
        end
    end
    return changed
end


local function strip_encrypted_value(value, state)
    if type(value) ~= "table" then return value end
    if value.type == "encrypted_content" then
        state.changed = true
        return { type = "input_text", text = "[encrypted state removed]" }
    end
    if value.encrypted_content ~= nil then
        value.encrypted_content = nil
        state.changed = true
    end
    for key, item in pairs(value) do
        if type(item) == "table" then
            value[key] = strip_encrypted_value(item, state)
        end
    end
    return value
end


local function sanitize_responses(data)
    local state = { changed = false }
    local input = data.input
    if type(input) == "table" then
        local kept = {}
        for _, item in ipairs(input) do
            local item_type = type(item) == "table" and item.type or nil
            if item_type == "reasoning"
                or item_type == "compaction"
                or item_type == "compaction_summary" then
                state.changed = true
            else
                kept[#kept + 1] = strip_encrypted_value(item, state)
            end
        end
        if #kept ~= #input then
            data.input = kept
        end
    end
    return state.changed
end


function _M.retry_with_rectified_body()
    if ngx.ctx.al_rectify_done then return end
    ngx.ctx.al_rectify_done = true
    if not RECTIFY_ENABLED then
        ngx.log(ngx.WARN, "C1RECT disabled by RECTIFY_ENABLED")
        return
    end

    local uri = ngx.var.uri
    ngx.req.read_body()
    local raw = ngx.ctx.al_forward_body
    if not raw then
        raw = ngx.req.get_body_data()
    end
    if not raw then
        local body_file = ngx.req.get_body_file()
        if body_file then
            local f = io.open(body_file, "rb")
            if f then
                raw = f:read("*a")
                f:close()
            end
        end
    end
    if not raw or raw == "" then return end

    local data = cjson.decode(raw)
    local changed = false
    if data then
        if uri == "/v1/messages" or uri == "/v1/messages/count_tokens" then
            changed = sanitize_anthropic(data)
        elseif uri == "/v1/chat/completions" then
            changed = sanitize_chat(data)
        elseif uri == "/v1/responses" or uri == "/v1/responses/compact" then
            changed = sanitize_responses(data)
        end
    end

    local body = raw
    if changed then
        mark_empty_arrays(data, raw)
        local ok, encoded = pcall(cjson.encode, data)
        if ok and encoded then
            body = encoded
        end
    end
    ngx.req.set_body_data(body)
    ngx.req.set_header("Content-Length", tostring(#body))
    ngx.req.clear_header("Transfer-Encoding")
    ngx.log(
        ngx.WARN,
        "C1RECT uri=" .. uri .. " changed=" .. tostring(changed)
            .. " in=" .. #raw .. " out=" .. #body
    )
end


return _M
