import pytest
from framework.tools.base import Tool, ToolResult
from framework.tools.permissions import check_permission
from framework.context.user import UserContext
from framework.errors import PermissionDeniedError


def _tool(perm=None):
    return Tool(name="t", description="d", parameters={}, fn=lambda **k: 1,
                required_permission=perm)


def test_no_required_permission_passes():
    check_permission(_tool(), UserContext(user_id="u"))  # no raise


def test_missing_permission_raises():
    with pytest.raises(PermissionDeniedError):
        check_permission(_tool("admin_only"), UserContext(user_id="u"))


def test_with_permission_passes():
    ctx = UserContext(user_id="u", permissions=frozenset({"admin_only"}))
    check_permission(_tool("admin_only"), ctx)  # no raise


def test_tool_to_schema_shape():
    t = Tool(name="get_risk", description="risk", parameters={"type": "object"},
             fn=lambda **k: 1)
    s = t.to_schema()
    assert s["type"] == "function"
    assert s["function"]["name"] == "get_risk"
    assert s["function"]["parameters"] == {"type": "object"}
