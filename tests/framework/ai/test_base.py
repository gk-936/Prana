from framework.ai.base import Role, ToolCall, Message, Usage, ChatResponse


def test_role_values():
    assert Role.USER == "user"
    assert Role.TOOL.value == "tool"


def test_message_defaults():
    m = Message(role=Role.USER, content="hi")
    assert m.tool_calls is None and m.tool_call_id is None


def test_usage_add_sums_tokens():
    a = Usage(prompt_tokens=10, completion_tokens=5, cost_usd=0.01)
    b = Usage(prompt_tokens=3, completion_tokens=2, cost_usd=0.02)
    total = a + b
    assert total.prompt_tokens == 13 and total.completion_tokens == 7
    assert abs(total.cost_usd - 0.03) < 1e-9


def test_usage_add_cost_none_when_either_missing():
    total = Usage(1, 1, None) + Usage(1, 1, 0.5)
    assert total.cost_usd is None


def test_chat_response_holds_tool_calls():
    tc = ToolCall(id="1", name="get_risk", arguments={})
    r = ChatResponse(content=None, tool_calls=[tc], usage=Usage(), raw={})
    assert r.tool_calls[0].name == "get_risk"
