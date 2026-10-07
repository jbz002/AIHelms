"""一次性全量对账：模型发布状态 → 个人主 Key 授权（平台 DB + LiteLLM 白名单）。

背景：find_personal_main_keys_for_model_sync 曾排除管理员（User.is_admin=False），
老代码授予管理员主 Key 的模型在取消发布后不被撤销，永久残留（平台 DB models
JSONB + LiteLLM 白名单），管理员可继续调用未发布模型。修复后管理员 Key 纳入
同一同步逻辑，本脚本遍历所有模型重算目标用户集合并对账，清理历史残留。

对账口径与 _sync_published_model_to_main_keys 一致：
- 未发布 / is_active=False → 从所有个人主 Key 撤销
- requires_approval → 仅保留已审批用户
- visibility_type=selected → 仅保留部门可见用户
- 其余（all）→ 授予全部启用 Key/启用用户

幂等：重复执行结果不变。逐模型独立事务，单模型失败不阻断其余。

运行：cd /app && python -m scripts.reconcile_model_key_access [--dry-run]
"""

import asyncio
import sys

from sqlalchemy import select

from core.database import async_session
from models.db import Model
from services import model_service


async def reconcile(session, model: Model, dry_run: bool) -> str:
    if not model.model_id:
        return "no model_id, skip"
    changed = await model_service._sync_published_model_to_main_keys(session, model)
    if dry_run:
        await session.rollback()
        status = "dry-run rolled back"
    else:
        await session.commit()
        status = "committed"
    return f"changed_keys={changed} ({status})"


async def main() -> None:
    dry_run = "--dry-run" in sys.argv
    async with async_session() as session:
        result = await session.execute(select(Model).order_by(Model.id))
        models = list(result.scalars().all())
    print(f"models: {len(models)}, dry_run={dry_run}")
    for model in models:
        async with async_session() as session:
            m = await session.get(Model, model.id)
            try:
                print(
                    f"model {m.id} {m.model_id}: {await reconcile(session, m, dry_run)}"
                )
            except Exception as e:  # noqa: BLE001
                await session.rollback()
                print(f"model {m.id} {m.model_id}: FAILED {e}")


if __name__ == "__main__":
    asyncio.run(main())
