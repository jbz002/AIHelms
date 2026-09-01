"""预算硬阻断测试：判定函数分支 + enforcement 协程的状态翻转与失败回退。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from services.litellm_client import LiteLLMError
from tasks import efficiency_tasks


def _row(
    *,
    key_id=1,
    litellm_key_id="sk-x",
    blocked_at=None,
    hard=True,
    limit=None,
    used=Decimal("0"),
    models_total=None,
    mcps_total=None,
    used_llm=Decimal("0"),
    used_mcp=Decimal("0"),
):
    return SimpleNamespace(
        id=key_id,
        litellm_key_id=litellm_key_id,
        budget_blocked_at=blocked_at,
        budget_hard_limit=hard,
        budget_limit=limit,
        budget_used=used,
        budget_models_total=models_total,
        budget_mcps_total=mcps_total,
        used_llm=used_llm,
        used_mcp=used_mcp,
    )


class FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.updates = []
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, stmt, params=None):
        if self._rows is not None:
            rows, self._rows = self._rows, None
            return rows
        self.updates.append(params)
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _patch_env(monkeypatch, session, budget_calls=None, fail=False):
    monkeypatch.setattr(
        efficiency_tasks, "get_worker_session_factory", lambda: lambda: session
    )

    async def fake_update(key_id, max_budget):
        if fail:
            raise LiteLLMError("litellm down")
        if budget_calls is not None:
            budget_calls.append((key_id, max_budget))

    import services.litellm_client as litellm_client

    monkeypatch.setattr(litellm_client, "update_key_budget", fake_update)


# --- _should_block_budget ---


def test_should_block_false_when_hard_limit_off() -> None:
    assert not efficiency_tasks._should_block_budget(
        hard_limit=False,
        used_total=Decimal("99"),
        limit=Decimal("1"),
        used_llm=Decimal("0"),
        models_total=None,
        used_mcp=Decimal("0"),
        mcps_total=None,
    )


def test_should_block_true_when_total_reaches_limit() -> None:
    assert efficiency_tasks._should_block_budget(
        hard_limit=True,
        used_total=Decimal("1.0"),
        limit=Decimal("1"),
        used_llm=Decimal("0"),
        models_total=None,
        used_mcp=Decimal("0"),
        mcps_total=None,
    )


def test_should_block_true_when_models_total_exceeded() -> None:
    assert efficiency_tasks._should_block_budget(
        hard_limit=True,
        used_total=Decimal("0"),
        limit=None,
        used_llm=Decimal("0.6"),
        models_total=Decimal("0.5"),
        used_mcp=Decimal("0"),
        mcps_total=None,
    )


def test_should_block_true_when_mcps_total_exceeded() -> None:
    assert efficiency_tasks._should_block_budget(
        hard_limit=True,
        used_total=Decimal("0"),
        limit=None,
        used_llm=Decimal("0"),
        models_total=None,
        used_mcp=Decimal("0.2"),
        mcps_total=Decimal("0.1"),
    )


def test_should_block_false_when_no_budget_configured() -> None:
    assert not efficiency_tasks._should_block_budget(
        hard_limit=True,
        used_total=Decimal("5"),
        limit=None,
        used_llm=Decimal("5"),
        models_total=None,
        used_mcp=Decimal("5"),
        mcps_total=None,
    )


# --- _enforce_budget_hard_limits ---


@pytest.mark.asyncio
async def test_enforce_blocks_over_limit_key(monkeypatch) -> None:
    session = FakeSession([_row(limit=Decimal("1"), used=Decimal("1.2"))])
    calls = []
    _patch_env(monkeypatch, session, calls)

    await efficiency_tasks._enforce_budget_hard_limits()

    assert calls == [("sk-x", 0.0)]
    assert session.updates == [{"id": 1}]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_enforce_releases_blocked_key_when_under_limit(monkeypatch) -> None:
    from datetime import datetime, timezone

    session = FakeSession(
        [
            _row(
                blocked_at=datetime.now(timezone.utc),
                limit=Decimal("1"),
                used=Decimal("0.3"),
            )
        ]
    )
    calls = []
    _patch_env(monkeypatch, session, calls)

    await efficiency_tasks._enforce_budget_hard_limits()

    assert calls == [("sk-x", None)]
    assert session.updates == [{"id": 1}]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_enforce_releases_key_when_hard_limit_disabled(monkeypatch) -> None:
    from datetime import datetime, timezone

    session = FakeSession(
        [_row(blocked_at=datetime.now(timezone.utc), hard=False, used=Decimal("99"))]
    )
    calls = []
    _patch_env(monkeypatch, session, calls)

    await efficiency_tasks._enforce_budget_hard_limits()

    assert calls == [("sk-x", None)]


@pytest.mark.asyncio
async def test_enforce_noop_when_state_consistent(monkeypatch) -> None:
    session = FakeSession([_row(limit=Decimal("1"), used=Decimal("0.2"))])
    calls = []
    _patch_env(monkeypatch, session, calls)

    await efficiency_tasks._enforce_budget_hard_limits()

    assert calls == []
    assert session.updates == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_enforce_litellm_failure_leaves_state_behind(monkeypatch) -> None:
    session = FakeSession([_row(limit=Decimal("1"), used=Decimal("2"))])
    _patch_env(monkeypatch, session, fail=True)

    await efficiency_tasks._enforce_budget_hard_limits()

    assert session.updates == []
    assert session.rollbacks == 1
