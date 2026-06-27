import pytest
from framework.ai.base import ChatResponse, Usage, Role, Message
from framework.ai.mock import MockProvider
from framework.errors import ProviderError


def test_mock_returns_scripted_responses_in_order():
    r1 = ChatResponse(content="first", usage=Usage())
    r2 = ChatResponse(content="second", usage=Usage())
    p = MockProvider(responses=[r1, r2])
    assert p.chat([Message(Role.USER, "x")]).content == "first"
    assert p.chat([Message(Role.USER, "y")]).content == "second"


def test_mock_records_calls():
    p = MockProvider(responses=[ChatResponse(content="ok")])
    p.chat([Message(Role.USER, "hi")], temperature=0.7)
    assert p.calls[0]["temperature"] == 0.7
    assert p.calls[0]["messages"][0].content == "hi"


def test_mock_raises_when_configured():
    p = MockProvider(error=ProviderError("down"))
    with pytest.raises(ProviderError):
        p.chat([Message(Role.USER, "x")])


def test_mock_satisfies_protocol():
    from framework.ai.base import LLMProvider
    assert isinstance(MockProvider(responses=[]), LLMProvider)
