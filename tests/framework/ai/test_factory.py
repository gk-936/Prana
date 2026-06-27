import pytest
from framework.config.settings import FrameworkSettings
from framework.ai.factory import build_provider
from framework.ai.fallback import FallbackProvider
from framework.ai.openrouter import OpenRouterProvider
from framework.errors import ConfigError


def test_single_provider_not_wrapped():
    s = FrameworkSettings(llm_providers=["openrouter"], openrouter_api_key="k", openrouter_model="m")
    assert isinstance(build_provider(s), OpenRouterProvider)


def test_multiple_wrapped_in_fallback():
    s = FrameworkSettings(llm_providers=["openrouter", "ollama"],
                          openrouter_api_key="k", openrouter_model="m", ollama_model="l")
    assert isinstance(build_provider(s), FallbackProvider)


def test_unknown_provider_raises():
    s = FrameworkSettings(llm_providers=["bogus"])
    with pytest.raises(ConfigError):
        build_provider(s)
