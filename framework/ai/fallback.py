from __future__ import annotations

from framework.ai.base import ChatResponse, LLMProvider, Message, ToolSchema
from framework.errors import ProviderError


class FallbackProvider:
    name = "fallback"

    def __init__(self, providers: list[LLMProvider]):
        if not providers:
            raise ProviderError("FallbackProvider requires at least one provider")
        self.providers = providers

    @property
    def supports_native_tools(self) -> bool:
        return self.providers[0].supports_native_tools

    def chat(self, messages: list[Message], *, tools: list[ToolSchema] | None = None,
             temperature: float = 0.2) -> ChatResponse:
        errors = []
        for provider in self.providers:
            try:
                use_tools = tools if provider.supports_native_tools else None
                return provider.chat(messages, tools=use_tools, temperature=temperature)
            except Exception as exc:  # noqa: BLE001 - try next provider
                errors.append(f"{provider.name}: {exc}")
        raise ProviderError("All providers failed: " + "; ".join(errors))
