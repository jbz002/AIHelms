"""docs-mcp-server REST client。

docs-mcp-server 提供 RESTful JSON API，路径以 /api 为前缀。
所有请求/响应均为标准 JSON，无需 superjson 包装。
"""

import json
import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

DOCS_MCP_TIMEOUT = 30.0


class DocsMcpError(Exception):
    pass


class DocsMcpClient:
    """调用 docs-mcp-server REST API 的客户端。"""

    def __init__(self) -> None:
        self._base_url = settings.docs_mcp_server_url.rstrip("/")

    async def _call(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: object | None = None,
    ) -> object:
        """调用 REST 接口。

        Args:
            method: HTTP 方法（GET, POST, DELETE 等）。
            path: API 路径（如 "/api/libraries"）。
            params: query 参数。
            json_data: JSON body。
        """
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=DOCS_MCP_TIMEOUT, proxy=None
            ) as client:
                logger.info(f"docs-mcp {method}: {url}")
                resp = await client.request(method, url, params=params, json=json_data)

                if resp.status_code >= 400:
                    logger.error(
                        "docs-mcp REST call failed",
                        extra={
                            "method": method,
                            "path": path,
                            "status": resp.status_code,
                            "body": resp.text[:500],
                        },
                    )
                    raise DocsMcpError(
                        f"docs-mcp {method} {path} failed: {resp.status_code} {resp.text[:200]}"
                    )

                return resp.json()
        except httpx.HTTPError as e:
            logger.error("docs-mcp connection error: %s - %s", path, str(e))
            raise DocsMcpError(f"docs-mcp {path} connection error: {e}") from e

    # ---- REST wrappers ----

    async def ping(self) -> dict:
        return await self._call("GET", "/api/health")

    async def list_libraries(self) -> list[dict]:
        return await self._call("GET", "/api/libraries")

    async def find_best_version(
        self, library: str, target_version: str | None = None
    ) -> dict:
        """查找最佳匹配版本。"""
        params: dict = {"library": library}
        if target_version is not None:
            params["targetVersion"] = target_version
        return await self._call(
            "GET", f"/api/libraries/{library}/versions/best", params=params
        )

    async def search(
        self,
        library: str,
        query: str,
        version: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        # 未指定版本时，先解析到实际版本（否则 search 只查无版本号文档）
        resolved_version: str | None = version
        if version is None:
            try:
                best = await self.find_best_version(library)
                resolved_version = (
                    best.get("bestMatch") if isinstance(best, dict) else None
                )
            except DocsMcpError:
                resolved_version = None

        params: dict = {
            "library": library,
            "query": query,
            "limit": str(limit),
        }
        if resolved_version is not None:
            params["version"] = resolved_version
        return await self._call("GET", "/api/search", params=params)

    async def get_jobs(self, status: str | None = None) -> dict:
        params = {"status": status} if status else None
        return await self._call("GET", "/api/jobs", params=params)

    async def cancel_job(self, job_id: str) -> dict:
        return await self._call("POST", f"/api/jobs/{job_id}/cancel")

    async def clear_completed_jobs(self) -> dict:
        return await self._call("POST", "/api/jobs/clear-completed")

    async def enqueue_scrape_job(
        self,
        library: str,
        version: str | None,
        options: dict,
    ) -> dict:
        logger.info(
            "enqueue_scrape_job input: %s",
            json.dumps(
                {"library": library, "version": version, "options": options},
                default=str,
                ensure_ascii=False,
            ),
        )
        body = {"library": library, "version": version, "options": options}
        return await self._call(
            "POST",
            "/api/jobs/scrape",
            json_data=body,
        )

    async def get_job_detail(self, job_id: str) -> dict:
        """获取单个作业详情。"""
        return await self._call("GET", f"/api/jobs/{job_id}")

    async def library_exists(self, library: str) -> bool:
        """检查文档库是否存在。"""
        try:
            await self._call("GET", f"/api/libraries/{library}/exists")
            return True
        except DocsMcpError:
            return False

    async def list_versions(self, status: str | None = None) -> list[dict]:
        """获取版本列表，可按状态筛选（逗号分隔）。"""
        params = {"status": status} if status else None
        return await self._call("GET", "/api/versions", params=params)

    async def find_versions_by_url(self, url: str) -> list[dict]:
        """根据 source URL 查找版本。"""
        return await self._call("GET", "/api/versions/by-url", params={"url": url})

    async def get_version_options(self, version_id: int) -> dict | None:
        """获取版本的抓取配置。"""
        return await self._call("GET", f"/api/versions/{version_id}/options")

    async def update_version_options(self, version_id: int, options: dict) -> None:
        """更新版本的抓取配置。"""
        await self._call(
            "PUT", f"/api/versions/{version_id}/options", json_data=options
        )

    async def remove_version(self, library: str, version: str) -> None:
        await self._call("DELETE", f"/api/libraries/{library}/versions/{version}")

    async def remove_version_documents(self, library: str, version: str) -> None:
        """删除版本下所有文档（保留版本记录）。"""
        await self._call(
            "DELETE", f"/api/libraries/{library}/versions/{version}/documents"
        )

    async def fetch_url(
        self,
        url: str,
        follow_redirects: bool = True,
        scrape_mode: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        """抓取单个 URL 并转换为 Markdown。

        Args:
            url: 要抓取的 URL。
            follow_redirects: 是否跟随重定向，默认 True。
            scrape_mode: HTML 处理策略 (fetch / playwright / auto)。
            headers: 自定义 HTTP 请求头。
        """
        body: dict = {"url": url, "followRedirects": follow_redirects}
        if scrape_mode is not None:
            body["scrapeMode"] = scrape_mode
        if headers is not None:
            body["headers"] = headers
        return await self._call("POST", "/api/fetch-url", json_data=body)

    async def ingest_raw(
        self,
        library: str,
        version: str | None,
        documents: list[dict],
    ) -> dict:
        """提交原始内容到 docs-mcp，由 docs-mcp 负责分块入库。

        Args:
            library: 文档库名。
            version: 版本号，可选。
            documents: 文档列表，每个包含 url, title, contentType, content。
        """
        return await self._call(
            "POST",
            "/api/ingest-raw",
            json_data={
                "library": library,
                "version": version or None,
                "documents": documents,
            },
        )

    async def ensure_library(
        self,
        library: str,
        version: str | None,
    ) -> dict:
        """确保 docs-mcp 中 library+version 存在（0 documents）。

        用于上传"仅提取"时在 docs-mcp 注册库，使其出现在 /api/libraries 列表。
        """
        return await self._call(
            "POST",
            "/api/libraries/ensure",
            json_data={"library": library, "version": version or None},
        )

    async def split_text(self, content: str, content_type: str) -> dict:
        """调用 docs-mcp 分块，返回块数（不入库）。

        用于上传"仅提取"对齐爬虫 crawlOnly 的分块计数。
        """
        return await self._call(
            "POST",
            "/api/split",
            json_data={"content": content, "contentType": content_type},
        )


docs_mcp_client = DocsMcpClient()
