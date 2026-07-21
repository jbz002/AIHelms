"""
自定义实体校验器 - 动态 Pydantic 模型构建
"""

import logging
from typing import Any, Dict, List

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """字段级校验错误"""

    def __init__(self, errors: List[Dict[str, str]]):
        self.errors = errors
        super().__init__(f"Validation failed with {len(errors)} errors")


def build_model(schema_definition: Dict[str, Any]) -> type[BaseModel]:
    """
    根据 JSON Schema 动态构建 Pydantic 模型

    Args:
        schema_definition: JSON Schema 格式的字段定义

    Returns:
        动态生成的 Pydantic 模型类
    """
    fields = {}

    for field_def in schema_definition.get("fields", []):
        field_name = field_def["name"]
        field_type = field_def["datatype"]
        required = field_def.get("required", False)

        # 类型映射
        python_type = _map_datatype_to_python(field_type, field_def)

        # 字段配置
        field_info = FieldInfo(
            default=... if required else None,
            description=field_def.get("label", ""),
        )

        if field_type == "enum" and field_def.get("enum_values"):
            field_info.description = f"Enum: {field_def['enum_values']}"

        fields[field_name] = (python_type, field_info)

    # 创建动态模型
    DynamicModel = create_model(
        "DynamicCustomEntity",
        __base__=BaseModel,
        **fields,
    )

    return DynamicModel


def _map_datatype_to_python(datatype: str, field_def: Dict[str, Any]) -> type:
    """映射字段类型到 Python 类型"""
    from typing import List

    mapping = {
        "string": str,
        "text": str,
        "number": float,
        "bool": bool,
        "enum": str,
        "array<string>": List[str],
    }

    return mapping.get(datatype, str)


def validate(
    type_key: str, data: Dict[str, Any], schema_definition: Dict[str, Any]
) -> Dict[str, Any]:
    """
    校验实体数据

    Args:
        type_key: 类型键
        data: 待校验数据
        schema_definition: Schema 定义

    Returns:
        校验后的数据

    Raises:
        ValidationError: 校验失败
    """
    try:
        model_class = build_model(schema_definition)
        validated = model_class(**data)
        return validated.model_dump()
    except Exception as e:
        errors = _extract_validation_errors(e)
        raise ValidationError(errors)


def _extract_validation_errors(exc: Exception) -> List[Dict[str, str]]:
    """从 Pydantic 异常提取字段级错误"""
    errors = []
    if hasattr(exc, "errors"):
        for err in exc.errors():
            errors.append(
                {
                    "field": ".".join(str(loc) for loc in err["loc"]),
                    "message": err["msg"],
                }
            )
    else:
        errors.append({"field": "unknown", "message": str(exc)})
    return errors


def check_schema_compatibility(
    old_schema: Dict[str, Any], new_schema: Dict[str, Any]
) -> Dict[str, Any]:
    """
    检查 Schema 变更兼容性

    Args:
        old_schema: 旧 Schema
        new_schema: 新 Schema

    Returns:
        兼容性报告 {"compatible": bool, "issues": List[str]}
    """
    issues = []

    old_fields = {f["name"]: f for f in old_schema.get("fields", [])}
    new_fields = {f["name"]: f for f in new_schema.get("fields", [])}

    # 检查删除的字段
    deleted_fields = set(old_fields.keys()) - set(new_fields.keys())
    if deleted_fields:
        issues.append(f"删除字段: {', '.join(deleted_fields)}")

    # 检查类型变更
    for field_name in old_fields.keys() & new_fields.keys():
        old_field = old_fields[field_name]
        new_field = new_fields[field_name]

        if old_field["datatype"] != new_field["datatype"]:
            issues.append(
                f"字段 '{field_name}' 类型从 {old_field['datatype']} 变更为 {new_field['datatype']}"
            )

        # 必填性变更
        if not old_field.get("required", False) and new_field.get("required", False):
            issues.append(f"字段 '{field_name}' 从可选变为必填")

    return {"compatible": len(issues) == 0, "issues": issues}
