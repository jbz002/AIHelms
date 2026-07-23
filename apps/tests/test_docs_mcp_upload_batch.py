"""批量上传文档（异步 + Celery）服务层集成测试。

走真实 DB（依赖 dev 中间件运行），mock docling-serve 与 docs-mcp-server，
覆盖 create_batch_records（建 pending 记录 + 暂存原始文件）与 process_upload
（提取 + 入库 + 删暂存文件）。
"""

import os
import uuid
from unittest.mock import AsyncMock

import pytest

from core.config import settings
from core.database import get_worker_session_factory
from repositories import doc_upload_repo
from services import doc_upload_service
from services.docling_client import docling_client
from services.docs_mcp_client import docs_mcp_client


def _session():
    return get_worker_session_factory()()


@pytest.mark.asyncio
async def test_create_batch_records_pends_and_stashes(monkeypatch, tmp_path):
    """批量建记录：N 条 pending，原始文件落盘到暂存目录。"""
    monkeypatch.setattr(settings, "uploads_storage_dir", str(tmp_path))

    library = f"batch-test-{uuid.uuid4().hex[:8]}"
    files = [(b"fake pdf bytes", "a.pdf"), (b"hello text", "b.txt")]

    async with _session() as s:
        records = await doc_upload_service.create_batch_records(
            s, files, library, None, None
        )
        await s.commit()

    assert len(records) == 2
    assert all(r["status"] == "pending" for r in records)
    for r in records:
        record_dir = os.path.join(str(tmp_path), "doc-upload-batch", str(r["id"]))
        assert os.path.isdir(record_dir)
        assert len(os.listdir(record_dir)) == 1


@pytest.mark.asyncio
async def test_process_upload_extracts_ingests_and_cleans(monkeypatch, tmp_path):
    """process_upload：提取（docling/纯文本）+ 入库 → completed，暂存目录删除。"""
    monkeypatch.setattr(settings, "uploads_storage_dir", str(tmp_path))
    monkeypatch.setattr(
        docling_client,
        "convert_file",
        AsyncMock(return_value="# 提取的 markdown"),
    )
    monkeypatch.setattr(
        docs_mcp_client, "split_text", AsyncMock(return_value={"chunks": 3})
    )
    monkeypatch.setattr(
        docs_mcp_client,
        "ingest_raw",
        AsyncMock(return_value={"ingested": 1, "chunks": 3}),
    )
    monkeypatch.setattr(docs_mcp_client, "ensure_library", AsyncMock(return_value=None))

    library = f"batch-test-{uuid.uuid4().hex[:8]}"
    files = [(b"fake pdf bytes", "a.pdf"), (b"hello text", "b.txt")]

    async with _session() as s:
        records = await doc_upload_service.create_batch_records(
            s, files, library, None, None
        )
        await s.commit()
        ids = [r["id"] for r in records]

        for rid in ids:
            await doc_upload_service.process_upload(s, rid, True)
        await s.commit()

        for rid in ids:
            rec = await doc_upload_repo.find_by_id(s, rid)
            assert rec is not None
            assert rec.status == "completed"
            assert rec.chunk_count == 3
            record_dir = os.path.join(str(tmp_path), "doc-upload-batch", str(rid))
            assert not os.path.exists(record_dir)


@pytest.mark.asyncio
async def test_process_upload_missing_stash_marks_failed(monkeypatch, tmp_path):
    """暂存文件丢失时 process_upload 置 failed，不抛异常。"""
    import shutil

    monkeypatch.setattr(settings, "uploads_storage_dir", str(tmp_path))

    library = f"batch-test-{uuid.uuid4().hex[:8]}"
    async with _session() as s:
        records = await doc_upload_service.create_batch_records(
            s, [(b"x", "a.txt")], library, None, None
        )
        await s.commit()
        rid = records[0]["id"]

        # 模拟暂存丢失
        shutil.rmtree(
            os.path.join(str(tmp_path), "doc-upload-batch", str(rid)),
            ignore_errors=True,
        )

        result = await doc_upload_service.process_upload(s, rid, True)
        await s.commit()

    assert result["status"] == "failed"
    assert "暂存丢失" in result["error_message"]
