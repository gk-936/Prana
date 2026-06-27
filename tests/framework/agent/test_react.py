from framework.agent.react import build_react_messages, parse_react_response
from framework.ai.base import Message, Role


def test_build_includes_tool_names_and_instruction():
    schemas = [{"type": "function", "function": {"name": "get_risk", "description": "x", "parameters": {}}}]
    out = build_react_messages([Message(Role.USER, "hi")], schemas)
    blob = " ".join(m.content for m in out)
    assert "get_risk" in blob and "answer" in blob.lower()


def test_parse_tool_call():
    calls, answer = parse_react_response('{"tool": "get_risk", "args": {"x": 1}}')
    assert answer is None
    assert calls[0].name == "get_risk" and calls[0].arguments == {"x": 1}


def test_parse_answer():
    calls, answer = parse_react_response('{"answer": "your risk is high"}')
    assert calls == [] and answer == "your risk is high"


def test_parse_tolerates_code_fence():
    calls, answer = parse_react_response('```json\n{"tool":"t","args":{}}\n```')
    assert calls[0].name == "t"


def test_parse_non_json_is_plain_answer():
    calls, answer = parse_react_response("Sorry, I cannot help.")
    assert calls == [] and answer == "Sorry, I cannot help."
