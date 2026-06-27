from __future__ import annotations

from framework.ai.base import ChatResponse, Message, ToolSchema
from framework.errors import ProviderError


class MockProvider:
    name = "mock"

    def __init__(
        self,
        responses: list[ChatResponse] | None = None,
        *,
        supports_native_tools: bool = True,
        error: Exception | None = None,
    ):
        self._responses = list(responses or [])
        self.supports_native_tools = supports_native_tools
        self._error = error
        self.calls: list[dict] = []

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
    ) -> ChatResponse:
        self.calls.append(
            {"messages": list(messages), "tools": tools, "temperature": temperature}
        )
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise ProviderError("MockProvider has no scripted responses left")
        return self._responses.pop(0)
