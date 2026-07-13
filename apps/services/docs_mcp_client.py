import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

DOCS_MCP_TIMEOUT = 30.0


def _unwrap_superjson(data: object) -> object:
    """递归解包 superjson {"json": value} 包装格式。"""
    if isinstance(data, dict):
        if "json" in data and len(data) == 1:
            return _unwrap_superjson(data["json"])
        return {k: _unwrap_superjson(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_unwrap_superjson(item) for item in data]
    return data


class DocsMcpClient:
    """调用 docs-mcp-server tRPC batch API 的客户端。"""

    def __init__(self) -> None:
        self._base_url = settings.docs_mcp_server_url

    async def _call(self, procedure: str, input_data: object = None) -> object:
        """调用单个 tRPC procedure，使用 httpBatchLink 格式。"""
        url = f"{self._base_url}/{procedure}"
        body: dict = {"0": {"json": input_data}}
        try:
            async with httpx.AsyncClient(
                timeout=DOCS_MCP_TIMEOUT, proxy=None
            ) as client:
                resp = await client.post(url, json=body)
                if resp.status_code >= 400:
                    logger.error(
                        "docs-mcp tRPC call failed",
                        extra={
                            "procedure": procedure,
                            "status": resp.status_code,
                            "body": resp.text[:500],
                        },
                    )
                    raise DocsMcpError(
                        f"docs-mcp {procedure} failed: {resp.status_code}"
                    )
                result = resp.json()
                inner = result.get("0", {}).get("result", {}).get("data", {})
                return _unwrap_superjson(inner)
        except httpx.HTTPError as e:
            logger.error("docs-mcp connection error: %s - %s", procedure, str(e))
            raise DocsMcpError(f"docs-mcp {procedure} connection error: {e}") from e

    async def ping(self) -> dict:
        return await self._call("ping")

    async def list_libraries(self) -> list[dict]:
        return await self._call("listLibraries")

    async def search(
        self,
        library: str,
        query: str,
        version: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        return await self._call(
            "search",
            {
                "library": library,
                "query": query,
                "version": version,
                "limit": limit,
            },
        )

    async def get_jobs(self, status: str | None = None) -> dict:
        return await self._call("getJobs", {"status": status})

    async def cancel_job(self, job_id: str) -> dict:
        return await self._call("cancelJob", {"id": job_id})

    async def clear_completed_jobs(self) -> dict:
        return await self._call("clearCompletedJobs")

    async def enqueue_scrape_job(
        self,
        library: str,
        version: str | None,
        options: dict,
    ) -> dict:
        return await self._call(
            "enqueueScrapeJob",
            {
                "library": library,
                "version": version,
                "options": options,
            },
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
        )

    async def remove_version(self, library: str, version: str) -> None:
        await self._call("removeVersion", {"library": library, "version": version})


class DocsMcpError(Exception):
    pass


docs_mcp_client = DocsMcpClient()
