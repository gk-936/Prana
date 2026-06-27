from framework.config.settings import FrameworkSettings


def test_defaults(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDERS", raising=False)
    s = FrameworkSettings()
    assert s.llm_providers == ["openrouter", "ollama"]
    assert s.agent_max_steps == 5


def test_llm_providers_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "gemini,ollama")
    s = FrameworkSettings()
    assert s.llm_providers == ["gemini", "ollama"]
