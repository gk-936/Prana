import pytest
from framework.ai.base import ChatResponse, Message, Role
from framework.ai.mock import MockProvider
from framework.ai.fallback import FallbackProvider
from framework.errors import ProviderError


def test_uses_first_working_provider():
    good = MockProvider(responses=[ChatResponse(content="ok")])
    chain = FallbackProvider([good])
    assert chain.chat([Message(Role.USER, "x")]).content == "ok"


def test_falls_through_to_next_on_error():
    bad = MockProvider(error=ProviderError("down"))
    good = MockProvider(responses=[ChatResponse(content="recovered")])
    chain = FallbackProvider([bad, good])
    assert chain.chat([Message(Role.USER, "x")]).content == "recovered"


def test_all_fail_raises_provider_error():
    chain = FallbackProvider([MockProvider(error=ProviderError("a")),
                              MockProvider(error=ProviderError("b"))])
    with pytest.raises(ProviderError):
        chain.chat([Message(Role.USER, "x")])


def test_supports_native_tools_from_first():
    chain = FallbackProvider([MockProvider(responses=[], supports_native_tools=False)])
    assert chain.supports_native_tools is False
