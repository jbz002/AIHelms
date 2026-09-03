# docs-mcp `search_docs` 卡死排查记录

> 日期：2026-09-01
> 环境：prod 服务器（131.131.2.10），docs-mcp-server 容器
> 现象：本地 MCP 工具 `search_docs` 调用 60s 超时，只回 SSE 心跳无结果

---

## 1. 问题背景

线上 AIHelms 的 docs-mcp-server 部署在 prod。本地 Claude Code 通过 MCP 配置
`http://131.131.2.10:30710/docs_mcp_server/mcp` 调用 `search_docs` 工具查 litellm 文档。

某次使用中 `search_docs` 执行 60s 超时，只回 SSE 心跳（`ping`），无实际结果。

排查方向最初怀疑「嵌入模型不能用了」，但最终根因是 **SQL 查询计划问题**，与嵌入模型无关。

---

## 2. 架构速览

```
本地 Claude Code
  └─ MCP http → openresty:30710/docs_mcp_server/mcp   (mcp 容器, 30751)
                    └─ mcp 容器 → worker REST 30750    (检索后端)
                          └─ worker → 讯飞 MaaS 嵌入 API (xop3qwen8bembedding)
```

- **mcp 容器**：`aihelms-docs-mcp-mcp`，MCP 协议层
- **worker 容器**：`aihelms-docs-mcp-worker`，REST 检索后端，`node dist/index.js worker --port 30750`
- **数据库**：`/data/documents.db`（SQLite + sqlite-vec + FTS5），litellm 库 12347 文档
- **嵌入模型**：`openai:xop3qwen8bembedding`（讯飞 MaaS，OpenAI 兼容），1024 维

---

## 3. 排查过程

### 3.1 确认 MCP 服务健康

MCP `initialize` 返回 200，`tools/list` 正常（4 个工具都在）。但 `search_docs` 执行 60s 超时。

**结论**：服务本身健康，问题在 `search_docs` 工具执行链路。

### 3.2 定位到 worker REST

worker 日志关键报错：`Failed to connect to server at http://127.0.0.1:30750` + `Search failed: fetch failed`。
`search_docs` 要连 worker 的 30750 检索服务。

### 3.3 排除嵌入模型（用户方向）

用户怀疑「嵌入模型不能用了」。逐项排查，**全部正常**：

| 检查 | 结果 |
|------|------|
| 嵌入 API 连通 | 200，0.2s 秒回 |
| 返回维度 | 1024，无 NaN |
| langchain 嵌入（worker 容器内） | 0.3s，dim 1024 |
| search 卡住时嵌入 API | 仍 0.2s |

### 3.4 定位到混合检索 SQL

`GET /api/search?library=litellm&version=1.74.0` 每次都卡 25s+（非间歇性）。
但嵌入、向量检索、单独 fts 都快。最终定位到 `findByContent` 的**完整混合检索 SQL** 卡死。

---

## 4. 测试脚本记录

> 所有脚本通过 `base64` 传到 worker 容器 `/tmp/` 后 `node` 执行（避免 heredoc 转义问题）。
> 数据库脚本用 worker 的 `better-sqlite3` + `sqlite-vec` 扩展（`/app/node_modules/sqlite-vec-linux-x64/vec0.so`）。

### 4.1 MCP 连通性测试（curl）

**测什么**：MCP 端点连通性、initialize、tools/list、search_docs 调用。

```bash
# initialize
curl -sm8 -X POST "http://131.131.2.10:30710/docs_mcp_server/mcp" \
  -H "x-litellm-api-key: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}'

# search_docs 计时
time curl -sm60 -X POST "$URL" ... -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_docs","arguments":{"library":"litellm","query":"supports_vision image"}}}'
```

**目的**：确认服务健康，定位问题在 `search_docs` 工具本身。

**结果**：initialize 200 正常，tools/list 正常，但 `search_docs` 60s 超时只回 SSE 心跳。

---

### 4.2 嵌入 API 维度测试（curl + python）

**测什么**：嵌入 API 实际返回的 embedding 维度、是否有 NaN。

```bash
KEY=$(grep "^OPENAI_API_KEY=" .env | cut -d= -f2-)
curl -sm30 -X POST "https://maas-api.cn-huabei-1.xf-yun.com/v2/embeddings" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"xop3qwen8bembedding","input":"test query","dimensions":1024,"encoding_format":"float"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); e=d['data'][0]['embedding']; print('dim=',len(e),'has_nan=',any(x!=x for x in e))"
```

**目的**：验证嵌入模型是否返回异常维度（若维度异常，`padVector`/`JSON.stringify` 会卡）。

**结果**：`dim=1024`，无 NaN。**嵌入模型正常**。

---

### 4.3 langchain 嵌入测试（`tmp_emb2.cjs`）

**测什么**：worker 容器内用 langchain `OpenAIEmbeddings` 调嵌入，模拟 worker 实际配置。

```js
const { OpenAIEmbeddings } = require("/app/node_modules/@langchain/openai");
const emb = new OpenAIEmbeddings({
  modelName: "xop3qwen8bembedding",
  timeout: 30000,
  dimensions: 1024,
  encodingFormat: "float",
  configuration: { baseURL: process.env.OPENAI_API_BASE, timeout: 30000 },
});
const v = await emb.embedQuery("test query");
console.log("dim", v.length, (Date.now()-t0)+"ms");
```

**目的**：排除 langchain 嵌入调用本身卡住（worker 内部嵌入链路）。

**结果**：`#0 dim=1024 322ms`，`#1 246ms`，`#2 148ms`。**嵌入调用 0.3s 秒回，完全正常**。

---

### 4.4 GET /api/search 多次计时（node fetch）

**测什么**：worker REST `/api/search` 是否间歇性卡。

```js
for (let i=0;i<3;i++){
  const ctl=new AbortController(); const to=setTimeout(()=>ctl.abort(),25000);
  const r=await fetch("http://127.0.0.1:30750/api/search?library=litellm&version=1.74.0&query=supports_vision%20image&limit=10",{signal:ctl.signal});
  ...
}
```

**目的**：确认 search 是间歇性卡还是每次都卡。

**结果**：3 次全部 25s 超时（AbortError）。**每次都卡，非间歇性**。

> 注意：`/api/search` 是 **GET** 不是 POST。之前用 POST 测返回 404，误导了排查方向。

---

### 4.5 数据库状态检查（`tmp_db.cjs`）

**测什么**：数据库大小、文档数、journal 模式、busy_timeout。

```js
const db = new Database("/data/documents.db", { readonly: true });
console.log("size", db.pragma("page_count",{simple:true})*db.pragma("page_size",{simple:true})/1024/1024, "MB");
console.log("documents", db.prepare("SELECT COUNT(*) c FROM documents").get().c);
```

**目的**：确认数据库状态，排除损坏/锁死。

**结果**：611MB，documents 12347，WAL 模式，busy_timeout 5000。**数据库正常**。

---

### 4.6 向量检索测试（`tmp_db2.cjs`）

**测什么**：sqlite-vec 向量检索单独耗时。

```js
db.loadExtension("/app/node_modules/sqlite-vec-linux-x64/vec0.so");
const t0=Date.now();
const vec=db.prepare("SELECT COUNT(*) c FROM documents_vec dv WHERE dv.library_id=? AND dv.version_id=? AND dv.embedding MATCH ? AND dv.k=?").get(libid,vid,JSON.stringify(emb),20);
console.log("vec count", vec.c, (Date.now()-t0)+"ms");
```

**目的**：排除向量检索卡住。

**结果**：`vec count 20 16ms`。**向量检索 16ms 快**。

---

### 4.7 完整混合检索 SQL 测试（`tmp_sql.cjs`）

**测什么**：`findByContent` 的完整 SQL（vec + fts + JOIN + NOT EXISTS）耗时。

```js
const SQL = `
WITH vec_distances AS NOT MATERIALIZED (...),
fts_scores AS (...)
SELECT d.id, d.content, d.metadata, p.url, ...,
  COALESCE(1/(1+v.vec_distance),0) vec_score,
  COALESCE(-MIN(f.fts_score,0),0) fts_score
FROM documents d
JOIN pages p ON d.page_id=p.id
LEFT JOIN vec_distances v ON d.id=v.id
LEFT JOIN fts_scores f ON d.id=f.id
WHERE (v.id IS NOT NULL OR f.id IS NOT NULL)
  AND NOT EXISTS (SELECT 1 FROM json_each(json_extract(d.metadata,'$.types')) je WHERE je.value='structural')`;
db.prepare(SQL).all(libid, vid, JSON.stringify(emb), 40, vid, ftsQuery, 20);
```

**目的**：定位卡点是否在完整 SQL。

**结果**：**卡 30s+（timeout 124）**。这是第一个关键突破——完整 SQL 卡死。

---

### 4.8 拆解 SQL：vec / fts 单独（`tmp_sql2.cjs`）

**测什么**：vec_distances 和 fts_scores（bm25）单独耗时。

```js
timed("vec_distances", () => db.prepare("SELECT rowid, distance FROM documents_vec dv WHERE ... MATCH ? ...").all(...));
timed("fts_scores", () => db.prepare("SELECT f.rowid, bm25(documents_fts,...) FROM documents_fts f JOIN documents d ... WHERE p.version_id=? AND documents_fts MATCH ? ...").all(...));
```

**目的**：拆解完整 SQL，看是 vec 还是 fts 卡。

**结果**：`vec_distances 16ms`，`fts_scores 4ms`。**单独都快**。卡点在组合。

---

### 4.9 拆解 JOIN（`tmp_sql3.cjs` / `tmp_sql4.cjs`）

**测什么**：vec JOIN documents、fts JOIN documents 单独耗时。

```js
// tmp_sql4.cjs
timed("vec_join_docs", () => db.prepare(`
  WITH vec_distances AS NOT MATERIALIZED (...)
  SELECT d.id, v.vec_distance FROM documents d
  LEFT JOIN vec_distances v ON d.id=v.id
  WHERE v.id IS NOT NULL`).all(...));
timed("fts_join_docs", () => db.prepare(`
  WITH fts_scores AS (...)
  SELECT d.id, f.fts_score FROM documents d
  LEFT JOIN fts_scores f ON d.id=f.id
  WHERE f.id IS NOT NULL`).all(...));
```

**目的**：确认是单个 JOIN 卡还是组合卡。

**结果**：`vec_join_docs 16ms`，`fts_join_docs 4ms`。**单独 JOIN 都快**。卡点在两个 CTE 组合。

---

### 4.10 vec_only / fts_only + NOT EXISTS（`tmp_sql5.cjs`）

**测什么**：单个 CTE + NOT EXISTS 过滤耗时。

```js
timed("vec_only", () => db.prepare(`
  WITH vec_distances AS NOT MATERIALIZED (...)
  SELECT d.id, v.vec_distance FROM documents d
  LEFT JOIN vec_distances v ON d.id=v.id
  WHERE v.id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM json_each(json_extract(d.metadata,'$.types')) je WHERE je.value='structural')`).all(...));
```

**目的**：确认 NOT EXISTS 单独是否卡。

**结果**：`vec_only 15ms`，`fts_only 4ms`。**单独 + NOT EXISTS 都快**。因为 `WHERE v.id IS NOT NULL` 先过滤到 40 行，NOT EXISTS 只对 40 行执行。

---

### 4.11 查询计划分析（`tmp_plan.cjs`）

**测什么**：完整 SQL 的 `EXPLAIN QUERY PLAN`。

```js
const plan = db.prepare("EXPLAIN QUERY PLAN " + SQL).all(...);
for (const r of plan) console.log(r.id, r.parent, r.notused, r.detail);
```

**目的**：看 SQLite 的查询计划，定位卡点。

**结果**（关键）：
```
SCAN d                          ← 全表扫描 documents (12347 行)
CORRELATED SCALAR SUBQUERY 3    ← 每行执行 NOT EXISTS 相关子查询
SCAN je VIRTUAL TABLE INDEX 1:  ← json_each 解析 metadata JSON
```

**根因确认**：`WHERE (v.id IS NOT NULL OR f.id IS NOT NULL)` 让 SQLite 无法下推过滤 → 全表扫描 + 每行 NOT EXISTS 相关子查询（json_each 解析 metadata）→ 卡 30s+。

---

### 4.12 验证根因：WHERE 改可下推形式（`tmp_sql6.cjs`）

**测什么**：完整 SQL 但 WHERE 改成 `v.id IS NOT NULL`（去掉 OR f）。

```js
timed("full_where_v_only", () => db.prepare(`
  WITH vec_distances AS NOT MATERIALIZED (...), fts_scores AS (...)
  SELECT ... FROM documents d JOIN pages p ...
  LEFT JOIN vec_distances v ON d.id=v.id LEFT JOIN fts_scores f ON d.id=f.id
  WHERE v.id IS NOT NULL
    AND NOT EXISTS (...)`).all(...));
```

**目的**：验证根因——OR 条件是否导致全表扫描。

**结果**：`full_where_v_only 19ms`。**确认根因**：OR 条件导致全表扫描卡。

---

### 4.13 修复方案验证（`tmp_fix.cjs`）

**测什么**：把 NOT EXISTS 下推到 vec_distances 和 fts_scores 两个 CTE，主查询去掉 NOT EXISTS。

```js
timed("FIX_pushed", () => db.prepare(`
  WITH vec_distances AS NOT MATERIALIZED (
    SELECT dv.rowid as id, dv.distance as vec_distance
    FROM documents_vec dv
    JOIN documents d ON dv.rowid = d.id
    WHERE dv.library_id=? AND dv.version_id=? AND dv.embedding MATCH ? AND dv.k=?
      AND NOT EXISTS (SELECT 1 FROM json_each(json_extract(d.metadata,'$.types')) je WHERE je.value='structural')
    ORDER BY dv.distance
  ),
  fts_scores AS (
    SELECT f.rowid as id, bm25(documents_fts,...) as fts_score
    FROM documents_fts f JOIN documents d ON f.rowid=d.id JOIN pages p ON d.page_id=p.id
    WHERE p.version_id=? AND documents_fts MATCH ?
      AND NOT EXISTS (SELECT 1 FROM json_each(json_extract(d.metadata,'$.types')) je WHERE je.value='structural')
    ORDER BY fts_score LIMIT ?
  )
  SELECT d.id, COALESCE(1/(1+v.vec_distance),0) vec_score, COALESCE(-MIN(f.fts_score,0),0) fts_score
  FROM documents d JOIN pages p ON d.page_id=p.id
  LEFT JOIN vec_distances v ON d.id=v.id LEFT JOIN fts_scores f ON d.id=f.id
  WHERE v.id IS NOT NULL OR f.id IS NOT NULL`).all(...));
```

**目的**：验证修复方案是否有效。

**结果**：`FIX_pushed 48ms`，rows=60。**修复有效**（原始卡 30s+ → 48ms）。

---

### 4.14 辅助：线程 CPU 采样（`tmp_thread.cjs`）

**测什么**：search 卡住时 worker 主线程 CPU 增量。

```js
// 采样两次 /proc/1/task/*/stat 的 utime/stime，看增量
const a = sample();
setTimeout(() => { const b = sample(); ... }, 3000);
```

**目的**：确认主线程是否 CPU 100%（同步计算卡住，而非网络等待）。

**结果**：`tid 1 cpu+ 3s`（3 秒内 +3s = 100% 单核）。**确认主线程同步计算卡住**。

---

### 4.15 辅助：v8 profiler 采样（`tmp_prof.mjs`）

**测什么**：用 inspector 9229 采样 search 卡住时的热点函数。

```js
const ws = new WebSocket(list[0].webSocketDebuggerUrl);
await send("Profiler.start");
await new Promise(r=>setTimeout(r,15000));
const { result } = await send("Profiler.stop");
// 聚合 selfTime，打印 top 热点
```

**目的**：定位卡点函数。

**结果**：采样卡在 `Profiler.stop`——**主线程忙到无法响应 inspector**，这本身印证 CPU 100%。改用查询计划分析定位根因。

---

## 5. 根因总结

**不是嵌入模型问题**。嵌入 API 0.2s、langchain 嵌入 0.3s、dim 1024 全正常。

根因在 `docs-mcp-server` 的 `DocumentStore.ts:2244` `findByContent` 混合检索 SQL：

```sql
WHERE (v.id IS NOT NULL OR f.id IS NOT NULL)
  AND NOT EXISTS (
    SELECT 1 FROM json_each(json_extract(d.metadata, '$.types')) je
    WHERE je.value = 'structural'
  )
```

**OR 条件让 SQLite 无法下推过滤** → 全表扫描 `documents`(12347 行) + 每行执行 NOT EXISTS 相关子查询（`json_each` 解析 metadata JSON）→ 卡 30s+，主线程 CPU 100%。

### 为什么之前不卡

之前 search 返回 `[]` 是因为 litellm 库 version=`1.74.0`，而 search 默认 `version="latest"` 匹配不上 → `getVersionId` 提前返回空，**没走完整 SQL**。现在传 `version=1.74.0` 匹配上了，走完整 SQL，暴露查询计划问题。

---

## 6. 修复方案

### 方案：NOT EXISTS 下推到 CTE

把 NOT EXISTS 过滤**下推到 vec_distances 和 fts_scores 两个 CTE**（通过 JOIN documents 过滤 structural），主查询去掉 NOT EXISTS。

```sql
WITH vec_distances AS NOT MATERIALIZED (
  SELECT dv.rowid as id, dv.distance as vec_distance
  FROM documents_vec dv
  JOIN documents d ON dv.rowid = d.id
  WHERE dv.library_id = ? AND dv.version_id = ?
    AND dv.embedding MATCH ? AND dv.k = ?
    AND NOT EXISTS (
      SELECT 1 FROM json_each(json_extract(d.metadata, '$.types')) je
      WHERE je.value = 'structural'
    )
  ORDER BY dv.distance
),
fts_scores AS (
  SELECT f.rowid as id, bm25(documents_fts, 10.0, 1.0, 5.0, 1.0) as fts_score
  FROM documents_fts f
  JOIN documents d ON f.rowid = d.id
  JOIN pages p ON d.page_id = p.id
  WHERE p.version_id = ? AND documents_fts MATCH ?
    AND NOT EXISTS (
      SELECT 1 FROM json_each(json_extract(d.metadata, '$.types')) je
      WHERE je.value = 'structural'
    )
  ORDER BY fts_score
  LIMIT ?
)
SELECT d.id, d.content, d.metadata, p.url, p.title,
  p.source_content_type, p.content_type,
  COALESCE(1 / (1 + v.vec_distance), 0) as vec_score,
  COALESCE(-MIN(f.fts_score, 0), 0) as fts_score
FROM documents d
JOIN pages p ON d.page_id = p.id
LEFT JOIN vec_distances v ON d.id = v.id
LEFT JOIN fts_scores f ON d.id = f.id
WHERE (v.id IS NOT NULL OR f.id IS NOT NULL)
```

**效果**：48ms（原始卡 30s+）。逻辑等价（structural 文档在 CTE 阶段已过滤）。

### 改动文件

- `src/store/DocumentStore.ts` 的 `findByContent` 方法（约 2244 行起）

### 部署步骤

```bash
# 1. 改源码后，本地 tar 同步到 prod
tar czf - --exclude='.git' --exclude='node_modules' --exclude='dist' . | ssh prod 'tar xzf - -C /home/ai/aihelms/docs-mcp-server'

# 2. rebuild + recreate worker
ssh prod 'cd /home/ai/aihelms/docs-mcp-server && docker buildx build --load --network host --ulimit nofile=1048576:1048576 -t docs-mcp-server:prod -f Dockerfile .'
ssh prod 'docker compose -p aihelms-docsmcp -f docker-compose.prod.yml up -d --force-recreate aihelms-docs-mcp-worker'

# 3. 验证
ssh prod 'docker exec aihelms-docs-mcp-worker node -e "fetch(\"http://127.0.0.1:30750/api/search?library=litellm&version=1.74.0&query=supports_vision%20image&limit=10\").then(r=>r.text()).then(t=>console.log(t.slice(0,100)))"'
```

---

## 7. 经验沉淀

1. **`/api/search` 是 GET 不是 POST**——用 POST 测返回 404，误导排查方向。先看 `DocumentManagementClient.ts` 确认 HTTP 方法。
2. **SQLite 的 OR 条件无法下推过滤**——`WHERE (a IS NOT NULL OR b IS NOT NULL)` 会全表扫描 + 相关子查询。混合检索 SQL 要避免这种写法。
3. **v8 profiler 采样在 CPU 100% 时不可用**——主线程忙到无法响应 inspector，`Profiler.stop` 卡住。改用 `EXPLAIN QUERY PLAN` 定位。
4. **嵌入模型排查要测 worker 容器内实际调用**——外部 curl 通不代表 worker 内部链路通。用 worker 的 `@langchain/openai` 直接测。
