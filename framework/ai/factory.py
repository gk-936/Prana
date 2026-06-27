from __future__ import annotations

from framework.ai.base import LLMProvider
from framework.ai.fallback import FallbackProvider
from framework.ai.gemini import GeminiProvider
from framework.ai.ollama import OllamaProvider
from framework.ai.openrouter import OpenRouterProvider
from framework.config.settings import FrameworkSettings
from framework.errors import ConfigError


def _build_one(name: str, s: FrameworkSettings) -> LLMProvider:
    if name == "openrouter":
        return OpenRouterProvider(s.openrouter_api_key, s.openrouter_model, s.openrouter_base_url)
    if name == "ollama":
        return OllamaProvider(s.ollama_model, s.ollama_base_url)
    if name == "gemini":
        return GeminiProvider(s.gemini_api_key, s.gemini_model)
    raise ConfigError(f"Unknown LLM provider '{name}'")


def build_provider(s: FrameworkSettings) -> LLMProvider:
    providers = [_build_one(n, s) for n in s.llm_providers]
    if not providers:
        raise ConfigError("No LLM providers configured")
    return providers[0] if len(providers) == 1 else FallbackProvider(providers)
