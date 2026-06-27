# framework/ — PRANA AI Backend Framework

Generic, provider-independent AI backend. PRANA consumes it; it knows nothing about PRANA.

## Quick start

    from framework import agent
    from framework.ai.factory import build_provider
    from framework.config.settings import FrameworkSettings
    from framework.tools.base import Tool, ToolRegistry
    from framework.context.user import UserContext

    registry = ToolRegistry()
    registry.register(Tool(name="get_orders", description="...",
                           parameters={"type": "object", "properties": {}},
                           fn=lambda *, ctx: [...]))
    provider = build_provider(FrameworkSettings())
    ag = agent(provider, registry)
    result = await ag.run("How many orders do I have?", UserContext(user_id="u1"))
    print(result.answer)

## Modules
- `ai/` — LLMProvider protocol + OpenRouter/Ollama/Gemini/Mock + FallbackProvider + factory
- `agent/` — reasoning loop (native function-calling + ReAct fallback)
- `tools/` — Tool, ToolRegistry, permission gate (checked before execution)
- `context/` — UserContext
- `messaging/` — MessageChannel protocol + WhatsApp/Email/Webhook/Mock + registry
- `persistence/` — UserRepository protocol + InMemory/SQLite
- `config/` — env-driven FrameworkSettings

## Extending
- New LLM provider: implement `LLMProvider`, add to `ai/factory.py`.
- New channel: implement `MessageChannel`, register in `MessagingRegistry`.
- New tool: `registry.register(Tool(...))`. Set `required_permission` to gate it.

## Guarantees
- The LLM never accesses data directly — only via registered tools.
- Tool identity args come from `UserContext`, not the model (no cross-user access).
- `framework/` never imports `prana/` (enforced by `.importlinter`).
- Fully testable with zero network calls (MockProvider, MockChannel).
