"""
自定义实体 Service 层
"""
import logging
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import CustomEntity, CustomEntityType
from repositories import custom_entity_repo
from services.custom_entity_validator import check_schema_compatibility, validate

logger = logging.getLogger(__name__)


# ─── Type CRUD ─────────────────────────────────────────────────────────────


async def list_types(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    is_active: bool | None = None,
    is_published: bool | None = None,
) -> Dict[str, Any]:
    """获取类型列表"""
    total = await custom_entity_repo.count_types(session, is_active, is_published)
    items = await custom_entity_repo.list_types(
        session, page, page_size, is_active, is_published
    )

    return {
        "items": [_serialize_type(t) for t in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_type(session: AsyncSession, type_id: int) -> Dict[str, Any]:
    """获取类型详情"""
    type_def = await custom_entity_repo.find_type_by_id(session, type_id)
    if not type_def:
        raise NotFoundError("custom_entity_type", type_id)
    return _serialize_type(type_def)


async def create_type(
    session: AsyncSession,
    type_key: str,
    display_name: str,
    description: str = "",
    icon: str = "🧩",
    schema_definition: Dict[str, Any] | None = None,
    searchable_fields: list | None = None,
    is_published: bool = False,
    created_by: int | None = None,
) -> Dict[str, Any]:
    """创建类型"""
    # 检查 type_key 是否存在
    existing = await custom_entity_repo.find_type_by_key(session, type_key)
    if existing:
        raise ConflictError(f"类型键 '{type_key}' 已存在")

    type_def = CustomEntityType(
        type_key=type_key,
        display_name=display_name,
        description=description,
        icon=icon,
        schema_definition=schema_definition or {},
        searchable_fields=searchable_fields or [],
        is_published=is_published,
        created_by=created_by,
    )

    type_def = await custom_entity_repo.create_type(session, type_def)
    await session.commit()
    await session.refresh(type_def)

    return _serialize_type(type_def)


async def update_type(
    session: AsyncSession,
    type_id: int,
    display_name: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    schema_definition: Dict[str, Any] | None = None,
    is_published: bool | None = None,
) -> Dict[str, Any]:
    """更新类型"""
    type_def = await custom_entity_repo.find_type_by_id(session, type_id)
    if not type_def:
        raise NotFoundError("custom_entity_type", type_id)

    # Schema 变更兼容性检查
    if schema_definition and schema_definition != type_def.schema_definition:
        compatibility = check_schema_compatibility(
            type_def.schema_definition, schema_definition
        )
        if not compatibility["compatible"]:
            entity_count = await custom_entity_repo.count_entities_by_type(
                session, type_id
            )
            if entity_count > 0:
                raise ValidationError(
                    f"Schema 变更不兼容，存在 {entity_count} 个实例。"
                    f"问题: {'; '.join(compatibility['issues'])}"
                )

    # 更新字段
    if display_name is not None:
        type_def.display_name = display_name
    if description is not None:
        type_def.description = description
    if icon is not None:
        type_def.icon = icon
    if schema_definition is not None:
        type_def.schema_definition = schema_definition
    if is_published is not None:
        type_def.is_published = is_published

    type_def = await custom_entity_repo.update_type(session, type_def)
    await session.commit()
    await session.refresh(type_def)

    return _serialize_type(type_def)


async def delete_type(session: AsyncSession, type_id: int) -> None:
    """删除类型"""
    type_def = await custom_entity_repo.find_type_by_id(session, type_id)
    if not type_def:
        raise NotFoundError("custom_entity_type", type_id)

    # 级联删除会自动处理实例（ON DELETE CASCADE）
    await custom_entity_repo.delete_type(session, type_id)
    await session.commit()


# ─── Entity CRUD ───────────────────────────────────────────────────────────


async def list_entities(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    type_key: str | None = None,
    is_published: bool | None = None,
) -> Dict[str, Any]:
    """获取实例列表"""
    total = await custom_entity_repo.count_entities(session, type_key, is_published)
    items = await custom_entity_repo.list_entities(
        session, page, page_size, type_key, is_published
    )

    return {
        "items": [_serialize_entity(e) for e in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_entity(session: AsyncSession, entity_id: int) -> Dict[str, Any]:
    """获取实例详情"""
    entity = await custom_entity_repo.find_entity_by_id(session, entity_id)
    if not entity:
        raise NotFoundError("custom_entity", entity_id)
    return _serialize_entity(entity)


async def create_entity(
    session: AsyncSession,
    type_key: str,
    name: str,
    data: Dict[str, Any],
    description: str = "",
    tags: list | None = None,
    is_published: bool = False,
    visibility_type: str = "all",
    requires_approval: bool = False,
    created_by: int | None = None,
) -> Dict[str, Any]:
    """创建实例"""
    # 获取类型定义
    type_def = await custom_entity_repo.find_type_by_key(session, type_key)
    if not type_def:
        raise ValidationError(f"类型 '{type_key}' 不存在")

    if not type_def.is_published:
        raise ValidationError(f"类型 '{type_key}' 未发布")

    # 校验数据
    try:
        validated_data = validate(type_key, data, type_def.schema_definition)
    except Exception as e:
        raise ValidationError(str(e))

    # 生成 content_text（用于搜索）
    content_text = _build_content_text(type_def, validated_data)

    # 发布门控：开启时发布动作转提交申请，资源先以未发布态落库
    from services import publish_review_service as _prs

    effective_published, submit_review_flag = await _prs.resolve_publish(
        session, is_published
    )

    entity = CustomEntity(
        type_id=type_def.id,
        type_key=type_key,
        name=name,
        data=validated_data,
        content_text=content_text,
        description=description,
        tags=tags or [],
        is_published=effective_published,
        visibility_type=visibility_type,
        requires_approval=requires_approval,
        created_by=created_by,
    )

    entity = await custom_entity_repo.create_entity(session, entity)

    # 门控开启时把发布动作转为评审申请（资源保持未发布）
    if submit_review_flag and created_by:
        await _prs.submit_review(
            session, _prs.ENTITY_CUSTOM, entity.id, created_by
        )

    await session.commit()
    await session.refresh(entity)

    # 触发 embedding 生成（模块 02 集成点）
    # await _trigger_embedding_generation(entity.id)

    return _serialize_entity(entity)


async def update_entity(
    session: AsyncSession,
    entity_id: int,
    name: str | None = None,
    data: Dict[str, Any] | None = None,
    description: str | None = None,
    tags: list | None = None,
    is_published: bool | None = None,
    visibility_type: str | None = None,
    actor_id: int | None = None,
) -> Dict[str, Any]:
    """更新实例"""
    entity = await custom_entity_repo.find_entity_by_id(session, entity_id)
    if not entity:
        raise NotFoundError("custom_entity", entity_id)

    # 获取类型定义用于校验
    type_def = await custom_entity_repo.find_type_by_key(session, entity.type_key)

    # 校验数据（如果有变更）
    if data is not None and data != entity.data:
        try:
            validated_data = validate(entity.type_key, data, type_def.schema_definition)
            entity.data = validated_data
            entity.content_text = _build_content_text(type_def, validated_data)
        except Exception as e:
            raise ValidationError(str(e))

    # 更新其他字段
    if name is not None:
        entity.name = name
    if description is not None:
        entity.description = description
    if tags is not None:
        entity.tags = tags
    if is_published is not None:
        was_published = entity.is_published
        effective = is_published
        # 发布门控：False→True 变更且门控开启时，转提交申请，保持未发布
        if is_published and not was_published and actor_id is not None:
            from services import publish_review_service, publish_settings_service

            if await publish_settings_service.is_gate_enabled(session):
                effective = False
                await publish_review_service.submit_review(
                    session,
                    publish_review_service.ENTITY_CUSTOM,
                    entity_id,
                    actor_id,
                )
        entity.is_published = effective
        # 同步可见性（复用现有逻辑）
        if effective and not entity.requires_approval:
            await _sync_visibility_to_all_keys(session, entity.id)
    if visibility_type is not None:
        entity.visibility_type = visibility_type

    entity = await custom_entity_repo.update_entity(session, entity)
    await session.commit()
    await session.refresh(entity)

    # 重新生成 embedding
    # await _trigger_embedding_generation(entity.id)

    return _serialize_entity(entity)


async def set_published(
    session: AsyncSession, entity_id: int, value: bool
) -> None:
    """审核通过后置 is_published（绕过门控，直接生效 + 可见性同步）。"""
    entity = await custom_entity_repo.find_entity_by_id(session, entity_id)
    if not entity:
        raise NotFoundError("custom_entity", entity_id)
    entity.is_published = value
    if value and not entity.requires_approval:
        await _sync_visibility_to_all_keys(session, entity.id)
    await session.flush()


async def delete_entity(session: AsyncSession, entity_id: int) -> None:
    """删除实例"""
    entity = await custom_entity_repo.find_entity_by_id(session, entity_id)
    if not entity:
        raise NotFoundError("custom_entity", entity_id)

    # 移除可见性
    await _remove_visibility_from_all_keys(session, entity_id)

    await custom_entity_repo.delete_entity(session, entity_id)
    await session.commit()


# ─── 辅助函数 ───────────────────────────────────────────────────────────────


def _build_content_text(type_def: CustomEntityType, data: Dict[str, Any]) -> str:
    """构建用于搜索的文本内容"""
    searchable = type_def.searchable_fields or []
    parts = []

    for field_name in searchable:
        if field_name in data:
            value = data[field_name]
            if isinstance(value, (list, dict)):
                parts.append(str(value))
            else:
                parts.append(str(value))

    return " ".join(parts)


async def _sync_visibility_to_all_keys(session: AsyncSession, entity_id: int) -> None:
    """同步可见性到所有主 Key（复用现有逻辑）"""
    from services import ai_key_service

    await ai_key_service.sync_public_resource_to_all_keys(
        session, "custom_entities", entity_id
    )


async def _remove_visibility_from_all_keys(
    session: AsyncSession, entity_id: int
) -> None:
    """从所有主 Key 移除可见性"""
    from services import ai_key_service

    await ai_key_service.remove_public_resource_from_all_keys(
        session, "custom_entities", entity_id
    )


def _serialize_type(type_def: CustomEntityType) -> Dict[str, Any]:
    """序列化类型对象"""
    return {
        "id": type_def.id,
        "type_key": type_def.type_key,
        "display_name": type_def.display_name,
        "description": type_def.description,
        "icon": type_def.icon,
        "schema_definition": type_def.schema_definition,
        "searchable_fields": type_def.searchable_fields,
        "is_active": type_def.is_active,
        "is_published": type_def.is_published,
        "created_by": type_def.created_by,
        "created_at": type_def.created_at.isoformat() if type_def.created_at else None,
        "updated_at": type_def.updated_at.isoformat() if type_def.updated_at else None,
    }


def _serialize_entity(entity: CustomEntity) -> Dict[str, Any]:
    """序列化实体对象"""
    return {
        "id": entity.id,
        "type_id": entity.type_id,
        "type_key": entity.type_key,
        "name": entity.name,
        "data": entity.data,
        "description": entity.description,
        "tags": entity.tags,
        "is_active": entity.is_active,
        "is_published": entity.is_published,
        "visibility_type": entity.visibility_type,
        "requires_approval": entity.requires_approval,
        "created_by": entity.created_by,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
        "updated_at": entity.updated_at.isoformat() if entity.updated_at else None,
    }
