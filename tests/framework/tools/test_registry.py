import asyncio
import pytest
from framework.tools.base import Tool, ToolRegistry, ToolResult
from framework.context.user import UserContext
from framework.errors import ToolError


def _reg(tool):
    r = ToolRegistry(); r.register(tool); return r


def test_register_duplicate_raises():
    t = Tool("a", "d", {}, fn=lambda **k: 1)
    r = ToolRegistry(); r.register(t)
    with pytest.raises(ToolError):
        r.register(t)


def test_get_missing_raises():
    with pytest.raises(ToolError):
        ToolRegistry().get("nope")


def test_schemas_returns_function_schemas():
    r = _reg(Tool("a", "d", {"type": "object"}, fn=lambda **k: 1))
    assert r.schemas()[0]["function"]["name"] == "a"


def test_execute_sync_tool_passes_ctx_and_args():
    def fn(*, ctx, x):
        return {"who": ctx.user_id, "x2": x * 2}
    r = _reg(Tool("a", "d", {}, fn=fn))
    res = asyncio.run(r.execute("a", {"x": 5}, UserContext(user_id="u1")))
    assert res.ok and res.data == {"who": "u1", "x2": 10}


def test_execute_async_tool():
    async def fn(*, ctx):
        return "async-ok"
    r = _reg(Tool("a", "d", {}, fn=fn))
    res = asyncio.run(r.execute("a", {}, UserContext(user_id="u1")))
    assert res.ok and res.data == "async-ok"


def test_execute_permission_denied_returns_error_result():
    r = _reg(Tool("a", "d", {}, fn=lambda **k: 1, required_permission="admin"))
    res = asyncio.run(r.execute("a", {}, UserContext(user_id="u1")))
    assert not res.ok and "permission" in res.error.lower()


def test_execute_tool_exception_returns_error_result():
    def boom(**k):
        raise ValueError("kaboom")
    r = _reg(Tool("a", "d", {}, fn=boom))
    res = asyncio.run(r.execute("a", {}, UserContext(user_id="u1")))
    assert not res.ok and "kaboom" in res.error
