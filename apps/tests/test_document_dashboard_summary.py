import pytest

from repositories import document_repo
from services import document_service


class FakeSession:
    """最小会话：repo 被 monkeypatch 后不实际触碰 DB。"""


@pytest.mark.asyncio
async def test_summary_aggregates_global_and_per_library(monkeypatch) -> None:
    rows = [
        {
            "library": "fastapi",
            "source_type": "crawl",
            "ingest_status": "ingested",
            "count": 3,
        },
        {
            "library": "fastapi",
            "source_type": "upload",
            "ingest_status": "pending",
            "count": 1,
        },
        {
            "library": "litellm",
            "source_type": "crawl",
            "ingest_status": "failed",
            "count": 2,
        },
    ]

    async def fake_rows(session):
        return rows

    monkeypatch.setattr(
        document_repo, "count_grouped_by_library_source_status", fake_rows
    )

    result = await document_service.get_dashboard_summary(FakeSession())

    assert result["global"]["total_documents"] == 6
    assert result["global"]["by_source"] == {"crawl": 5, "upload": 1}

    assert result["by_library"]["fastapi"]["by_source"] == {"crawl": 3, "upload": 1}
    assert result["by_library"]["fastapi"]["by_status"] == {"ingested": 3, "pending": 1}
    assert result["by_library"]["fastapi"]["total_documents"] == 4
    assert result["by_library"]["litellm"]["total_documents"] == 2


@pytest.mark.asyncio
async def test_summary_empty_tables_returns_zeros(monkeypatch) -> None:
    async def fake_rows(session):
        return []

    monkeypatch.setattr(
        document_repo, "count_grouped_by_library_source_status", fake_rows
    )

    result = await document_service.get_dashboard_summary(FakeSession())

    assert result["global"]["total_documents"] == 0
    assert result["global"]["by_source"] == {}
    assert result["by_library"] == {}
