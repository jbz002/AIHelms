"""P1 授权矩阵编译器：纯函数规则覆盖（无 DB）。"""

from services.mcp_authz_service import GrantView, compile_grants

SERVERS = {1: "docs", 2: "supply_cloud", 3: "product_order", 9: "unpublished"}
PUBLISHED = {1, 2, 3}
PUBLIC = {1}
APPROVED = {2: {"supplier_search", "order_search"}, 3: {"po_search"}}


def _compile(grants, subjects, toolsets=None, names=None):
    return compile_grants(
        grants,
        subjects,
        server_names=names or SERVERS,
        published_ids=PUBLISHED,
        public_ids=PUBLIC,
        approved_tools=APPROVED,
        toolset_items=toolsets or {},
        toolset_names={tid: f"ts{tid}" for tid in (toolsets or {})},
    )


def test_public_server_always_visible():
    out = _compile([], {("public", None)})
    assert out.servers == ["docs"]
    assert out.tool_permissions == {}


def test_user_server_grant_has_no_tool_restriction():
    out = _compile(
        [GrantView("user", 7, "server", 2, "allow")],
        {("public", None), ("user", 7)},
    )
    assert out.servers == ["docs", "supply_cloud"]
    assert out.tool_permissions == {}


def test_role_grant_applies_to_role_member():
    grants = [GrantView("role", 5, "server", 2, "allow")]
    member = _compile(grants, {("public", None), ("user", 7), ("role", 5)})
    outsider = _compile(grants, {("public", None), ("user", 8)})
    assert "supply_cloud" in member.servers
    assert "supply_cloud" not in outsider.servers


def test_dept_grant_applies_to_member():
    grants = [GrantView("dept", 3, "server", 3, "allow")]
    out = _compile(grants, {("public", None), ("dept", 3)})
    assert out.servers == ["docs", "product_order"]


def test_deny_overrides_allow():
    grants = [
        GrantView("role", 5, "server", 2, "allow"),
        GrantView("user", 7, "server", 2, "deny"),
    ]
    out = _compile(grants, {("public", None), ("user", 7), ("role", 5)})
    assert "supply_cloud" not in out.servers


def test_deny_can_remove_public_server():
    out = _compile(
        [GrantView("user", 7, "server", 1, "deny")],
        {("public", None), ("user", 7)},
    )
    assert out.servers == []


def test_toolset_narrows_to_approved_tools():
    toolsets = {11: {(2, "supplier_search"), (2, "not_approved")}}
    out = _compile(
        [GrantView("role", 5, "toolset", 11, "allow")],
        {("public", None), ("role", 5)},
        toolsets=toolsets,
    )
    assert out.servers == ["docs", "supply_cloud"]
    assert out.tool_permissions == {"supply_cloud": ["supplier_search"]}
    assert out.toolsets == ["ts11"]


def test_toolset_with_no_approved_tool_drops_server():
    toolsets = {11: {(2, "not_approved")}}
    out = _compile(
        [GrantView("user", 7, "toolset", 11, "allow")],
        {("public", None), ("user", 7)},
        toolsets=toolsets,
    )
    assert out.servers == ["docs"]


def test_server_grant_wins_over_toolset_narrowing():
    """同时有 server 级授权时，toolset 不再收窄（与计划口径一致）。"""
    toolsets = {11: {(2, "supplier_search")}}
    out = _compile(
        [
            GrantView("role", 5, "server", 2, "allow"),
            GrantView("user", 7, "toolset", 11, "allow"),
        ],
        {("public", None), ("user", 7), ("role", 5)},
        toolsets=toolsets,
    )
    assert "supply_cloud" in out.servers
    assert out.tool_permissions == {}


def test_unpublished_or_catalog_server_never_compiled():
    out = _compile(
        [GrantView("user", 7, "server", 9, "allow")],
        {("public", None), ("user", 7)},
    )
    assert "unpublished" not in out.servers


def test_policy_hash_tracks_content():
    base = _compile(
        [GrantView("user", 7, "server", 2, "allow")],
        {("public", None), ("user", 7)},
    )
    same = _compile(
        [GrantView("user", 7, "server", 2, "allow")],
        {("public", None), ("user", 7)},
    )
    other = _compile(
        [GrantView("user", 7, "server", 3, "allow")],
        {("public", None), ("user", 7)},
    )
    assert base.policy_hash == same.policy_hash
    assert base.policy_hash != other.policy_hash
