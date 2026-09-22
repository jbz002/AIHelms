# MCP server 接入 AIHelms 平台规范（工具命名 · annotations.title · instructions）

> 2026-09-22 立。适用对象：**所有要在 AIHelms 网关注册 MCP server 的开发者**（自研或第三方部署）。
> 一份文档两个读者：开发者读 §1–§4（怎么写工具），平台维护者守 §5（网关透传契约与 label 命名红线）。
> 消费端（ai-assistant / LibreChat）的行为见 §6，仅供知悉。

---

## 1. 心智模型：一个工具有三层"名字"

| 层 | 字段 | 给谁看 | 约束 |
|---|---|---|---|
| 函数名 | `name` | **模型 / 程序**（工具调用 id、日志、代码引用） | ASCII `^[a-zA-Z0-9_-]{1,64}$`，snake_case，不可中文 |
| 显示名 | `annotations.title` | **最终用户**（客户端 UI 的工具行、工具卡） | 任意文字，建议中文、动词开头、≤8 字 |
| 说明 | `description`（每个工具）/ `instructions`（server 整体） | **模型**（决定何时路由到这个工具/服务） | description 首句定位划界；instructions 写服务边界 |

三层各司其职，**不要互相串**：title 不进模型上下文（往 title 塞指令没用）；description 不是显示名（用户基本看不到它）。

---

## 2. annotations.title：怎么写

### TypeScript（@modelcontextprotocol/sdk）

`server.tool()` 第四参 annotations 对象（现成示例：docs-mcp-server `src/mcp/mcpServer.ts`）：

```ts
server.tool(
  "search_docs",                      // name：给模型的函数名
  "Search up-to-date official documentation ...",  // description：给模型的说明
  { library: z.string(), ... },       // 输入 schema
  {
    title: "搜索库文档",               // ← annotations.title：给用户看的显示名
    readOnlyHint: true,
    destructiveHint: false,
  },
  async (args) => { ... },
);
```

### Python（官方 SDK FastMCP，`mcp.server.fastmcp`）

`@mcp.tool()` 支持 `title=` 直传（jlowin 的 `fastmcp` 2.x 包同形）：

```python
@mcp.tool(title="搜索知识库")
async def search_knowledge(query: str, top_k: int = 5) -> str:
    """给模型看的工具说明：首句写清定位与边界。"""
    ...
```

server 整体说明（给模型的 initialize 握手字段）：

```python
mcp = FastMCP(
    name="enterprise-kb",
    instructions="企业内部知识库检索服务：…… 不含任何外部库文档。",
)
```

### 命名建议

- 面向最终用户的语言（当前用户群 → 中文），动词开头："搜索知识库""列出文档库""抓取网页"。
- 每个工具都要设；不设的客户端会裸显函数名（如 `lookup_chunk`）。
- 只影响显示，**改 title 零风险**（不进工具 id、不进模型），随时可调。

---

## 3. description：给模型的路由说明

多个 MCP server 工具集相似时（如"搜文档"类），模型靠 description 区分。规范：

1. **首句定位划界**，先说"是什么、不是什么"：
   - ✅ `Search up-to-date official documentation for an open-source library/framework/package (third-party library docs only — NOT internal company documents). ...`
   - ❌ `Search documentation.`（和知识库检索的描述无法区分）
2. 主体保留用法示例（参数怎么填、典型 query），这部分对模型选参价值最大。
3. 语言跟随模型侧主流（当前公司模型中文场景，中英均可，**划界句必须有**）。

## 4. instructions：server 整体定位（可选但推荐）

MCP initialize 握手的 `instructions` 字段，客户端会整段注入系统提示（如 LibreChat 的 `serverInstructions: true` 通道）。写法：

- 一段话讲清：本服务检索什么、**不检索什么**（把边界划给同类服务）。
- docs-mcp-server 示例（2026-09-22）：`Up-to-date documentation retrieval for open-source libraries, frameworks, and packages ... It does NOT index internal company knowledge bases — ...`

---

## 5. 平台契约（AIHelms 网关义务）⚠️

### 5.1 注册 label 命名红线

**label 禁止包含子串 `_mcp_`**。

原因：LibreChat 用 `_mcp_` 作工具 id 分隔符（`<toolName>_mcp_<serverName>`）。网关会把 label 作为前缀改写到每个工具名（`{label}-search_docs`），label 含 `_mcp_` 会污染工具名、触发消费端切分错乱——`docs_mcp_server` 这个 label 已实际踩坑（builder 里四个工具全显示成 "docs"，2026-09-22 才修完，见 ai-assistant 仓 `docs/2026-08-20-MCP工具id分隔符碰撞修复（fork语义分叉）.md` 后记）。

**label 用连字符**：`docs-mcp-server` ✅ / `docs_mcp_server` ❌。

### 5.2 网关透传契约

LiteLLM 网关（30710）转发 MCP 时**必须原样透传**，不得改写或丢弃：

| 字段 | 2026-09-22 实测 | 说明 |
|---|---|---|
| `tools[].annotations`（含 title） | ✅ 透传 | 上游显示名的唯一通道，丢了 title 就白设 |
| initialize `instructions` | ✅ 透传 | 上游 server 整体定位的通道 |
| `tools[].description` | ✅ 透传 | 模型路由依据 |

网关**会改写**的（这是行为不是 bug，消费端已适配）：工具名加 `{label}-` 前缀、`serverInfo.name` 改为 label。升级 LiteLLM / 更换网关实现时，须回归验证上表三项透传（握手探测法见 ai-assistant 仓 2026-09-22 部署记录）。

---

## 6. 消费端行为（ai-assistant / LibreChat，知悉即可）

ai-assistant 已完成 annotations.title 适配（2026-09-22，commit `01bd48ffe`）：

- **透传链**：上游 annotations → api MCP 目录缓存 → data-provider schema → 前端。
- **显示优先级**：内置白名单映射（自研核心工具的官方中文文案）> **上游 annotations.title** > 剥 label 前缀的函数名。第三方工具的显示名由其 title 决定；自研工具白名单优先，第三方无法借同名覆盖。
- **展示面**：Agent 构建器工具卡/工具列表、聊天工具行。
- server 整体说明：自研 yaml 管的 server 走 `serverInstructions` 字符串（运营方手写，优先级最高）；用户连接级的第三方 server 只有工具 description 一条通道（LibreChat 剥离用户连接的 serverInstructions 字段，属上游设计）。

详细决策记录：ai-assistant 仓（jbz002/ai-assistant，Private）`docs/2026-08-20-MCP工具id分隔符碰撞修复（fork语义分叉）.md` 后记二。
