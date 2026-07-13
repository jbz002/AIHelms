"""docs-mcp-server tRPC client。

docs-mcp-server 的 tRPC 端点挂载在 /api 前缀下，采用单 procedure 请求格式：
- query procedure: GET /api/{name}?input=[superjson]
- mutation procedure: POST /api/{name}，body {"input": superjson}
- 返回值: {"result":{"data":{"json": ...}}}（superjson 变换包装）
"""

import json
import logging
from urllib.parse import quote, urlencode

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

DOCS_MCP_TIMEOUT = 30.0


def _wrap_superjson(data: object) -> str:
    """将 Python 对象序列化为 superjson v2 格式的 JSON 字符串。

    superjson v2 serialize() 始终返回 {"json": value}。
    服务端 superjson.deserialize() 要求顶层有 "json" 键才能正确解包。

    用于 GET query 参数时：服务端先 URL 解码 → JSON.parse → superjson.deserialize
    用于 POST body 时：直接作为 JSON body 发给服务端 superjson.deserialize
    """
    return json.dumps({"json": data}, default=str, ensure_ascii=False)


def _unwrap_result(raw: object) -> object:
    """解包 tRPC 返回值: {"result":{"data": superjson_encoded}} → decoded。

    superjson 可能带 meta 字段（{"json": value, "meta": {...}}），
    也可能只有 {"json": value}，两种情况都要提取出 value。
    """
    if not isinstance(raw, dict):
        return raw
    result = raw.get("result")
    if not isinstance(result, dict):
        return raw
    data = result.get("data")
    if not isinstance(data, dict):
        return raw
    if "json" not in data:
        return raw
    return data["json"]


# tRPC procedure 类型映射：哪些是 mutation（POST），哪些是 query（GET）
_MUTATION_PROCEDURES = frozenset({
    "enqueueScrapeJob",
    "enqueueRefreshJob",
    "cancelJob",
    "clearCompletedJobs",
    "removeVersion",
})


class DocsMcpError(Exception):
    pass


class DocsMcpClient:
    """调用 docs-mcp-server tRPC API 的客户端。"""

    def __init__(self) -> None:
        self._base_url = settings.docs_mcp_server_url.rstrip("/")

    async def _call(
        self,
        procedure: str,
        input_data: object | None = None,
        method: str = "GET",
    ) -> object:
        """调用单个 tRPC procedure。

        Args:
            procedure: procedure 名称（如 "listLibraries"）。
            input_data: 输入参数（dict 或 None）。
            method: "GET" 或 "POST"。
        """
        url = f"{self._base_url}/api/{procedure}"
        try:
            async with httpx.AsyncClient(
                timeout=DOCS_MCP_TIMEOUT, proxy=None
            ) as client:
                if method == "GET":
                    if input_data is not None:
                        encoded = _wrap_superjson(input_data)
                        # URL 编码 query 参数值（JSON 字符串含特殊字符/中文）
                        url = f"{url}?input={quote(encoded, safe='')}"
                    logger.info(f"docs-mcp GET: {url}")
                    resp = await client.get(url)
                else:
                    # POST body 也是 superjson 格式 {"json": input_data}
                    payload = {"json": input_data} if input_data is not None else {}
                    logger.info(
                        f"docs-mcp POST: {url}, payload: {json.dumps(payload, default=str, ensure_ascii=False)[:1000]}"
                    )
                    logger.debug(
                        f"docs-mcp POST detailed: procedure={procedure}, input_data={json.dumps(input_data, default=str, ensure_ascii=False) if input_data else 'None'}, full_payload={json.dumps(payload, default=str, ensure_ascii=False)}"
                    )
                    resp = await client.post(url, json=payload)

                if resp.status_code >= 400:
                    logger.error(
                        "docs-mcp tRPC call failed",
                        extra={
                            "procedure": procedure,
                            "method": method,
                            "status": resp.status_code,
                            "body": resp.text[:500],
                        },
                    )
                    raise DocsMcpError(
                        f"docs-mcp {procedure} failed: {resp.status_code} {resp.text[:200]}"
                    )

                raw = resp.json()
                return _unwrap_result(raw)
        except httpx.HTTPError as e:
            logger.error("docs-mcp connection error: %s - %s", procedure, str(e))
            raise DocsMcpError(
                f"docs-mcp {procedure} connection error: {e}"
            ) from e

    # ---- procedure wrappers ----

    async def ping(self) -> dict:
        return await self._call("ping", method="GET")

    async def list_libraries(self) -> list[dict]:
        return await self._call("listLibraries", method="GET")

    async def find_best_version(
        self, library: str, target_version: str | None = None
    ) -> dict:
        """查找最佳匹配版本。"""
        input_data: dict = {"library": library}
        if target_version is not None:
            input_data["targetVersion"] = target_version
        return await self._call("findBestVersion", input_data, method="GET")

    async def search(
        self,
        library: str,
        query: str,
        version: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        # 未指定版本时，先解析到实际版本（否则 searchStore 只查无版本号文档）
        resolved_version: str | None = version
        if version is None:
            try:
                best = await self.find_best_version(library)
                resolved_version = best.get("bestMatch") if isinstance(best, dict) else None
            except DocsMcpError:
                resolved_version = None

        return await self._call(
            "search",
            {
                "library": library,
                "query": query,
                "version": resolved_version,
                "limit": limit,
            },
            method="GET",
        )

    async def get_jobs(self, status: str | None = None) -> dict:
        input_data: dict | None = None
        if status is not None:
            input_data = {"status": status}
        return await self._call("getJobs", input_data, method="GET")

    async def cancel_job(self, job_id: str) -> dict:
        return await self._call("cancelJob", {"id": job_id}, method="POST")

    async def clear_completed_jobs(self) -> dict:
        return await self._call("clearCompletedJobs", method="POST")

    async def enqueue_scrape_job(
        self,
        library: str,
        version: str | None,
        options: dict,
    ) -> dict:
        input_data = {
            "library": library,
            "version": version,
            "options": options,
        }
        logger.info(f"enqueue_scrape_job input: {json.dumps(input_data, default=str, ensure_ascii=False)}")
        return await self._call(
            "enqueueScrapeJob",
            input_data,
            method="POST",
        )

    async def enqueue_refresh_job(
        self,
        library: str,
        version: str | None,
        options: dict | None = None,
    ) -> dict:
        return await self._call(
            "enqueueRefreshJob",
            {
                "library": library,
                "version": version,
                "options": options,
            },
            method="POST",
        )

    async def remove_version(self, library: str, version: str) -> None:
        await self._call(
            "removeVersion",
            {"library": library, "version": version},
            method="POST",
        )


docs_mcp_client = DocsMcpClient()
