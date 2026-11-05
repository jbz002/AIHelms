"""LLM 日志口径测试：模型组与供应商身份（093 迁移）。

日志三层语义分离：模型组（无路由前缀）/ 供应商身份 / 路由方言。
LiteLLM SpendLogs 里 model 是解析后的上游串（openai/xxx），model_group 才是
客户端请求的模型组；供应商要靠 deployment→credential→provider 还原。

测试数据全部带 TEST_PREFIX 标记，teardown 按前缀清理。
"""

from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import select, text

from core.database import get_worker_session_factory
from models.db import LlmCallLog
from repositories import usage_log_repo
from tasks import llm_log_tasks

TEST_PREFIX = "pytest-logidentity-"
MODEL_ID = f"{TEST_PREFIX}model"
MODEL_GROUP = f"{TEST_PREFIX}group"
SUPPLIER_NAME = f"{TEST_PREFIX}supplier"
LITELLM_MODEL_ID = f"{TEST_PREFIX}uuid"
REQUEST_ID = f"{TEST_PREFIX}req-0001"


async def _cleanup(session) -> None:
    await session.execute(
        text("DELETE FROM aihelms.llm_call_logs WHERE request_id LIKE :p"),
        {"p": f"{TEST_PREFIX}%"},
    )
    await session.execute(
        text('DELETE FROM public."LiteLLM_SpendLogs" WHERE request_id LIKE :p'),
        {"p": f"{TEST_PREFIX}%"},
    )
    await session.execute(
        text("DELETE FROM aihelms.credentials WHERE credential_name LIKE :p"),
        {"p": f"{TEST_PREFIX}%"},
    )
    await session.execute(
        text("DELETE FROM aihelms.models WHERE model_id LIKE :p"),
        {"p": f"{TEST_PREFIX}%"},
    )
    await session.execute(
        text("DELETE FROM aihelms.providers WHERE name LIKE :p"),
        {"p": f"{TEST_PREFIX}%"},
    )
    await session.commit()


@pytest_asyncio.fixture
async def seeded_log():
    """造一条供应商链路 + SpendLogs 记录，跑 reconcile 后返回断言所需 id。"""
    factory = get_worker_session_factory()
    async with factory() as session:
        await _cleanup(session)
        provider_id = await session.scalar(
            text(
                "INSERT INTO aihelms.providers (name, provider_type) "
                "VALUES (:name, 'other') RETURNING id"
            ),
            {"name": SUPPLIER_NAME},
        )
        credential_id = await session.scalar(
            text(
                "INSERT INTO aihelms.credentials "
                "(credential_name, provider_id, credential_values, credential_info) "
                "VALUES (:name, :provider_id, '{}', '{\"format\": \"openai\"}') "
                "RETURNING id"
            ),
            {"name": f"{TEST_PREFIX}credential", "provider_id": provider_id},
        )
        model_pk = await session.scalar(
            text(
                "INSERT INTO aihelms.models (name, model_id, category) "
                "VALUES (:name, :model_id, 'chat') RETURNING id"
            ),
            {"name": f"{TEST_PREFIX}Model", "model_id": MODEL_ID},
        )
        deployment_id = await session.scalar(
            text(
                "INSERT INTO aihelms.model_deployments "
                "(model_id, credential_id, litellm_model_id, litellm_params) "
                "VALUES (:model_pk, :credential_id, :litellm_model_id, '{}') "
                "RETURNING id"
            ),
            {
                "model_pk": model_pk,
                "credential_id": credential_id,
                "litellm_model_id": LITELLM_MODEL_ID,
            },
        )
        moment = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        await session.execute(
            text(
                'INSERT INTO public."LiteLLM_SpendLogs" '
                "(request_id, call_type, api_key, spend, total_tokens, "
                'prompt_tokens, completion_tokens, "startTime", "endTime", '
                "model, model_group, model_id, custom_llm_provider, status) "
                "VALUES (:rid, 'acompletion', :api_key, 0, 10, 6, 4, "
                ":moment, :moment, :model, :model_group, :litellm_model_id, "
                "'openai', 'success')"
            ),
            {
                "rid": REQUEST_ID,
                "api_key": f"{TEST_PREFIX}key",
                "moment": moment,
                "model": f"openai/{MODEL_GROUP}",
                "model_group": MODEL_GROUP,
                "litellm_model_id": LITELLM_MODEL_ID,
            },
        )
        await session.commit()

    await llm_log_tasks._reconcile()

    yield {
        "provider_id": provider_id,
        "deployment_id": deployment_id,
        "model_pk": model_pk,
    }

    async with factory() as session:
        await _cleanup(session)


@pytest_asyncio.fixture
async def session():
    async with get_worker_session_factory()() as session:
        yield session


@pytest_asyncio.fixture
async def synced_log(seeded_log, session):
    result = await session.execute(
        select(LlmCallLog).where(LlmCallLog.request_id == REQUEST_ID)
    )
    return result.scalar_one_or_none()


@pytest_asyncio.fixture
async def seeded(synced_log, session):
    """组合：确保日志已同步，同时暴露 session 供查询断言。"""
    return synced_log


async def test_llm_log_sync_stores_model_group_and_supplier_identity(seeded):
    assert seeded is not None
    assert seeded.model == f"openai/{MODEL_GROUP}"
    assert seeded.model_group == MODEL_GROUP
    assert seeded.provider == "openai"
    assert seeded.provider_name == SUPPLIER_NAME


async def test_llm_log_filter_matches_model_group_without_route_prefix(seeded, session):
    logs = await usage_log_repo.find_llm_logs(
        session, page=1, page_size=20, model=MODEL_GROUP
    )
    assert [log.request_id for log in logs] == [REQUEST_ID]


async def test_llm_log_filter_matches_supplier_name(seeded, session):
    logs = await usage_log_repo.find_llm_logs(
        session, page=1, page_size=20, provider=SUPPLIER_NAME
    )
    assert [log.request_id for log in logs] == [REQUEST_ID]


async def test_llm_log_filters_list_display_values(seeded, session):
    filters = await usage_log_repo.llm_log_filters(session)
    assert MODEL_GROUP in [item["value"] for item in filters["models"]]
    assert SUPPLIER_NAME in filters["providers"]
