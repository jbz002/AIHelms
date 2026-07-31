from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Department, User, UserDepartment


async def find_all_active(session: AsyncSession) -> list[Department]:
    result = await session.execute(
        select(Department)
        .where(Department.is_active == True)
        .order_by(Department.sort_order, Department.id)
    )
    return list(result.scalars().all())


async def find_by_id(session: AsyncSession, dept_id: int) -> Department | None:
    result = await session.execute(select(Department).where(Department.id == dept_id))
    return result.scalar_one_or_none()


async def create(session: AsyncSession, dept: Department) -> Department:
    session.add(dept)
    await session.flush()
    await session.refresh(dept)
    return dept


async def count_children(session: AsyncSession, dept_id: int) -> int:
    result = await session.execute(
        select(func.count(Department.id)).where(
            Department.parent_id == dept_id, Department.is_active == True
        )
    )
    return result.scalar_one()


async def count_members(session: AsyncSession, dept_id: int) -> int:
    result = await session.execute(
        select(func.count(UserDepartment.id)).where(
            UserDepartment.department_id == dept_id
        )
    )
    return result.scalar_one()


async def find_members(
    session: AsyncSession, dept_id: int
) -> list[tuple[User, UserDepartment]]:
    result = await session.execute(
        select(User, UserDepartment)
        .join(UserDepartment, UserDepartment.user_id == User.id)
        .where(UserDepartment.department_id == dept_id)
        .order_by(UserDepartment.is_manager.desc(), User.id)
    )
    return list(result.tuples().all())


async def find_membership(
    session: AsyncSession, user_id: int, dept_id: int
) -> UserDepartment | None:
    result = await session.execute(
        select(UserDepartment).where(
            UserDepartment.user_id == user_id, UserDepartment.department_id == dept_id
        )
    )
    return result.scalar_one_or_none()


async def add_member(session: AsyncSession, user_id: int, dept_id: int) -> None:
    session.add(UserDepartment(user_id=user_id, department_id=dept_id))
    await session.flush()


async def remove_member(session: AsyncSession, user_id: int, dept_id: int) -> None:
    await session.execute(
        delete(UserDepartment).where(
            UserDepartment.user_id == user_id, UserDepartment.department_id == dept_id
        )
    )


async def clear_managers(session: AsyncSession, dept_id: int) -> None:
    await session.execute(
        update(UserDepartment)
        .where(UserDepartment.department_id == dept_id)
        .values(is_manager=False)
    )


async def set_managers(
    session: AsyncSession, dept_id: int, user_ids: list[int]
) -> None:
    if user_ids:
        await session.execute(
            update(UserDepartment)
            .where(
                UserDepartment.department_id == dept_id,
                UserDepartment.user_id.in_(user_ids),
            )
            .values(is_manager=True)
        )


async def find_managers(session: AsyncSession, dept_id: int) -> list[User]:
    result = await session.execute(
        select(User)
        .join(UserDepartment, UserDepartment.user_id == User.id)
        .where(
            UserDepartment.department_id == dept_id, UserDepartment.is_manager == True
        )
    )
    return list(result.scalars().all())


async def find_paginated(
    session: AsyncSession, page: int, page_size: int, keyword: str | None = None
) -> tuple[list[Department], int]:
    stmt_count = select(func.count(Department.id)).where(Department.is_active == True)
    stmt_list = (
        select(Department)
        .where(Department.is_active == True)
        .order_by(Department.sort_order, Department.id)
    )
    if keyword:
        pattern = f"%{keyword}%"
        stmt_count = stmt_count.where(Department.name.ilike(pattern))
        stmt_list = stmt_list.where(Department.name.ilike(pattern))
    total = (await session.execute(stmt_count)).scalar_one()
    offset = (page - 1) * page_size
    stmt_list = stmt_list.limit(page_size).offset(offset)
    result = await session.execute(stmt_list)
    return list(result.scalars().all()), total


async def upsert_by_aihub_id(
    session: AsyncSession, aihub_id: str, name: str | None
) -> Department | None:
    """按 aihub_department_id 查/建本地部门。SSO 登录同步用。

    命中则更新 name 后返回；未命中且 name 非空则新建；未命中且 name 为空返回 None
    （不建空壳部门）。并发首登用 ON CONFLICT DO NOTHING 兜底，避免 IntegrityError
    回滚整个 SSO 事务。
    """
    existing = await session.execute(
        select(Department).where(Department.aihub_department_id == aihub_id)
    )
    dept = existing.scalar_one_or_none()
    if dept is not None:
        if name and dept.name != name:
            dept.name = name
        return dept
    if not name:
        return None
    stmt = (
        pg_insert(Department)
        .values(name=name, aihub_department_id=aihub_id, is_active=True)
        .on_conflict_do_nothing(index_elements=["aihub_department_id"])
    )
    await session.execute(stmt)
    await session.flush()
    created = await session.execute(
        select(Department).where(Department.aihub_department_id == aihub_id)
    )
    return created.scalar_one_or_none()


async def set_user_aihub_department(
    session: AsyncSession, user_id: int, local_dept_id: int | None
) -> None:
    """把 user 的 AIHub 来源部门关联替换为 local_dept_id。

    只清该 user 当前关联中、部门 aihub_department_id 非空的旧记录（AIHub 来源），
    不动 admin 手动加的本地部门。local_dept_id 为 None 时仅清旧 AIHub 关联。
    """
    old_ids = await session.execute(
        select(UserDepartment.department_id)
        .join(Department, Department.id == UserDepartment.department_id)
        .where(
            UserDepartment.user_id == user_id,
            Department.aihub_department_id.isnot(None),
        )
    )
    old_aihub_dept_ids = list(old_ids.scalars().all())
    if old_aihub_dept_ids:
        await session.execute(
            delete(UserDepartment).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id.in_(old_aihub_dept_ids),
            )
        )
    if local_dept_id is None:
        return
    already = await session.execute(
        select(UserDepartment.id).where(
            UserDepartment.user_id == user_id,
            UserDepartment.department_id == local_dept_id,
        )
    )
    if already.scalar_one_or_none() is not None:
        return
    session.add(UserDepartment(user_id=user_id, department_id=local_dept_id))
    await session.flush()
