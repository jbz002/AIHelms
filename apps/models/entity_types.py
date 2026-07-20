"""跨实体类型词汇表，供评分等跨实体引用使用。

模块 02 的统一搜索用裸字符串 ["mcp_server","mcp_tool","skill"]；
本模块为评分等新功能提供单一来源，未来扩展 custom_entity / agent 仅改此处。
"""

MCP_SERVER = "mcp_server"
SKILL = "skill"
# 未来扩展：CUSTOM_ENTITY = "custom_entity"; AGENT = "agent"

RATABLE_ENTITY_TYPES: frozenset[str] = frozenset({MCP_SERVER, SKILL})

# 空串表示「仅评分，无分类反馈」
FEEDBACK_TYPES: frozenset[str] = frozenset({"", "bug", "suggestion", "praise"})
