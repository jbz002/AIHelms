"""docling-serve HTTP client。

调用 docling-serve 将二进制文档（PDF/DOCX/PPTX 等）转为 Markdown。
docling-serve 作为独立 Docker 容器运行，不侵入主应用依赖。
"""

import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class DoclingError(Exception):
    pass


class DoclingClient:
    """调用 docling-serve REST API 的客户端。"""

    def __init__(self) -> None:
        self._base_url = settings.docling_serve_url.rstrip("/")
        self._timeout = settings.docling_convert_timeout

    async def convert_file(
        self,
        file_bytes: bytes,
        file_name: str,
        content_type: str = "application/pdf",
        do_ocr: bool = True,
    ) -> str:
        """将二进制文件转换为 Markdown。

        Args:
            file_bytes: 文件原始字节。
            file_name: 文件名（含扩展名）。
            content_type: MIME 类型。
            do_ocr: 是否启用 OCR。

        Returns:
            转换后的 Markdown 文本。

        Raises:
            DoclingError: 转换失败或 docling-serve 不可用。
        """
        url = f"{self._base_url}/v1/convert/file"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, proxy=None) as client:
                files = {"files": (file_name, file_bytes, content_type)}
                data = {
                    "to_formats": "md",
                    "do_ocr": "true" if do_ocr else "false",
                    # OCR 引擎与语言必须显式给：serve 默认 preset=auto、语言为空，
                    # 走纯英文模型，中文截图/扫描件整片识别成噪声（实测同一张中文
                    # 截图：不传 → "2 y / Iu litellm POST"，传 → "浏览 API 接口"）。
                    "ocr_preset": settings.docling_ocr_preset,
                    "ocr_lang": [
                        lang.strip()
                        for lang in settings.docling_ocr_lang.split(",")
                        if lang.strip()
                    ],
                }
                # 图片描述走 docling 实例侧预设（docling-serve.yaml 里定义，指向
                # AIHelms 网关视觉模型）。预设名必须显式给：serve 的 "default" 别名
                # 只认 docling 内置预设名，指向自定义预设会 404。
                if settings.docling_picture_description:
                    data["do_picture_description"] = "true"
                    data["picture_description_preset"] = (
                        settings.docling_picture_description_preset
                    )
                    # 阈值只认请求字段：jobkit 用它无条件覆盖预设里的
                    # picture_area_threshold，不传就是 0.05（小示意图会被跳过）。
                    data["picture_description_area_threshold"] = str(
                        settings.docling_picture_description_area_threshold
                    )
                logger.info(
                    "docling convert: %s (%s, ocr=%s, picture_description=%s)",
                    file_name,
                    content_type,
                    do_ocr,
                    settings.docling_picture_description,
                )
                resp = await client.post(url, files=files, data=data)

                if resp.status_code >= 400:
                    raise DoclingError(
                        f"docling-serve 转换失败: {resp.status_code} {resp.text[:200]}"
                    )

                result = resp.json()
                status = result.get("status", "")

                if status == "failure":
                    errors = result.get("errors", [])
                    detail = "; ".join(str(e) for e in errors[:3])
                    raise DoclingError(f"docling-serve 转换失败: {detail}")

                md_content = ""
                doc = result.get("document", {})
                if isinstance(doc, dict):
                    md_content = doc.get("md_content", "")

                if not md_content.strip():
                    raise DoclingError(f"docling-serve 转换结果为空: {file_name}")

                return md_content

        except DoclingError:
            raise
        except httpx.ConnectError as e:
            raise DoclingError(f"无法连接 docling-serve ({self._base_url}): {e}") from e
        except httpx.TimeoutException as e:
            raise DoclingError(
                f"docling-serve 转换超时 ({self._timeout}s): {file_name}"
            ) from e
        except httpx.HTTPError as e:
            raise DoclingError(f"docling-serve 请求异常: {e}") from e


docling_client = DoclingClient()
