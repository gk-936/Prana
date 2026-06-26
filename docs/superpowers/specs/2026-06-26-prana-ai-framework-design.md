# PRANA AI Backend Framework — Design Spec

**Date:** 2026-06-26
**Status:** Approved (design); pending written-spec review
**Author:** Gokul + Claude (brainstorming session)

## 1. Goal & Scope

Build a generic, pip-installable `framework/` package that powers PRANA's conversational
AI layer, designed so it can be reused by future projects with only project-specific
business logic added on top.

The framework knows **nothing** about PRANA. PRANA is a *consumer* of the framework.

### Driving use case (first slice)

End-to-end "explain my risk over WhatsApp":

```
WhatsApp "why is my risk high?"
  -> webhook verifies signature, looks up user by phone (SQLite)
  -> agent.run -> LLM decides to call get_risk -> tool runs PRANASystem
  -> LLM explains the CCRI/RDS numbers in plain language, in the user's locale
  -> messaging.send(whatsapp) -> user gets the reply
```

### Chosen parameters

- **LLM providers:** OpenRouter, Ollama, Google Gemini, + Mock (testing).
- **Messaging channels:** WhatsApp, Email (SMTP), Webhook, + Mock (testing).
- **Tool-calling:** native function-calling when the provider supports it, prompt-based
  ReAct fallback otherwise (so local Ollama models without tool support still work).
- **User identity:** SQLite via a `UserRepository` interface (Protocol + SQLite + in-memory).
- **Provider failure:** config-defined fallback chain (e.g. openrouter -> gemini -> ollama),
  with light per-provider retry/backoff.
- **Code home:** `framework/` subdirectory in the existing PRANA repo. Generic but
  pragmatic (YAGNI — only the chosen providers/channels are built; interfaces allow
  extension). Split into its own repo later if it stabilizes.

### Architectural approach

**Approach A — Protocol-first hexagonal.** Each layer is a `typing.Protocol`; concrete
adapters implement it; the agent depends only on Protocols. Config selects concrete
implementations at startup. (Rejected: B — thin wrapper over existing `LLMClient`, fails
the config-swappable goal; C — adopt LangChain, contradicts owning the foundation.)

## 2. Package Structure & Boundaries

```
framework/                          # generic, pip-installable, zero PRANA knowledge
├── ai/
│   ├── base.py            # LLMProvider Protocol, Message, ChatResponse, ToolCall, Usage
│   ├── openrouter.py      # OpenRouterProvider
│   ├── ollama.py          # OllamaProvider
│   ├── gemini.py          # GeminiProvider
│   ├── mock.py            # MockProvider (scriptable, no network)
│   ├── fallback.py        # FallbackProvider (implements LLMProvider, walks chain)
│   └── factory.py         # build provider(s) from config
├── agent/
│   ├── base.py            # Agent — the reasoning/tool loop
│   └── result.py          # AgentResult (answer, tool_calls, usage, trace)
├── tools/
│   ├── base.py            # Tool, ToolResult, ToolRegistry
│   └── permissions.py     # PermissionError, permission check
├── context/
│   └── user.py            # UserContext (pydantic)
├── messaging/
│   ├── base.py            # MessageChannel Protocol, OutboundMessage, DeliveryResult
│   ├── whatsapp.py        # WhatsAppChannel
│   ├── email.py           # EmailChannel (SMTP)
│   ├── webhook.py         # WebhookChannel
│   ├── mock.py            # MockChannel (captures sends)
│   └── registry.py        # MessagingRegistry + send(channel=...)
├── persistence/
│   ├── base.py            # UserRepository Protocol
│   ├── sqlite.py          # SQLiteUserRepository
│   └── memory.py          # InMemoryUserRepository (tests)
├── config/
│   └── settings.py        # pydantic-settings, env-driven provider selection
└── errors.py              # framework exception hierarchy

prana/                              # CONSUMER of framework (existing engine stays)
├── ai_tools/
│   └── risk.py            # get_risk tool wrapping PRANASystem
├── bot/
│   ├── whatsapp_webhook.py # FastAPI router: webhook -> agent -> reply
│   └── bootstrap.py        # wires registry/provider/messaging/repo at startup
└── ... (existing modules unchanged)

tests/framework/                    # unit + integration, all mock-based
```

### Boundary rules

1. `framework/` imports nothing from `prana/`. Ever. Enforced by an import-linter test
   that fails the build on violation.
2. The agent depends only on Protocols, never concrete adapters.
3. PRANA's existing scoring engine (`prana/`) is untouched; the agent reaches it **only**
   through the registered `get_risk` tool. The LLM never directly accesses the engine or DB.
4. `backend/llm.py`'s `LLMClient` is superseded by `framework/ai` but left in place until
   the new path works green, then its caller (sleep-checkin extraction) is migrated and the
   old file deleted (cleanup step).

## 3. Core Interfaces

### `framework/ai/base.py`

```python
class Role(StrEnum): SYSTEM; USER; ASSISTANT; TOOL

@dataclass
class ToolCall: id: str; name: str; arguments: dict

@dataclass
class Message:
    role: Role; content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

@dataclass
class Usage: prompt_tokens: int; completion_tokens: int; cost_usd: float | None

@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall]
    usage: Usage
    raw: dict

class LLMProvider(Protocol):
    name: str
    supports_native_tools: bool
    def chat(self, messages: list[Message], *, tools: list[dict] | None = None,
             temperature: float = 0.2, **kw) -> ChatResponse: ...
    def stream(self, messages, **kw) -> Iterator[str]: ...   # optional; default raises
```

One `chat()` signature for all providers. `tools=None` -> plain chat. If
`supports_native_tools` is False, the agent uses the prompt-ReAct fallback instead of
passing `tools`.

### `framework/tools/base.py`

```python
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict           # JSON Schema
    fn: Callable[..., Any]      # sync or async
    required_permission: str | None = None

@dataclass
class ToolResult: ok: bool; data: Any; error: str | None = None

class ToolRegistry:
    def register(self, tool: Tool) -> None
    def get(self, name: str) -> Tool
    def schemas(self) -> list[dict]                         # for the LLM
    async def execute(self, name, args, ctx: UserContext) -> ToolResult   # permission FIRST
```

Permission check happens in `execute()` before `fn` runs — enforced centrally so no tool
can forget it. Sync `fn` runs in a threadpool; async `fn` is awaited.

### `framework/context/user.py`

```python
class UserContext(BaseModel):
    user_id: str
    organization_id: str | None = None
    username: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str = "user"
    permissions: frozenset[str] = frozenset()
    locale: str = "en"
    timezone: str = "UTC"
    preferences: dict = {}
    metadata: dict = {}      # app-specific (PRANA puts lat/lon/onboarding here)
    def has_permission(self, perm: str) -> bool
```

### `framework/messaging/base.py`

```python
@dataclass
class OutboundMessage: recipient: str; body: str; template: str | None = None; data: dict = {}
@dataclass
class DeliveryResult: ok: bool; provider_message_id: str | None; error: str | None

class MessageChannel(Protocol):
    name: str
    async def send(self, msg: OutboundMessage) -> DeliveryResult: ...
```

### `framework/persistence/base.py`

```python
class UserRepository(Protocol):
    async def get_by_phone(self, phone: str) -> UserContext | None: ...
    async def get(self, user_id: str) -> UserContext | None: ...
    async def upsert(self, user: UserContext) -> None: ...
```

### Deliberate calls

- Tools can be sync or async; the registry handles both.
- Cost/token tracking lives in `Usage` per-call; the agent sums it into `AgentResult`.
  No separate monitoring module in slice 1 — just expose the numbers.

## 4. The Agent Loop

`Agent.run(user_message, ctx, history=None) -> AgentResult`

```
messages = [system_prompt(ctx), *history, user(user_message)]
for step in range(max_steps):          # default 5, prevents infinite loops
    if provider.supports_native_tools:
        resp = provider.chat(messages, tools=registry.schemas())
        tool_calls = resp.tool_calls
    else:
        resp = provider.chat(prompt_with_react_instructions(messages, registry))
        tool_calls = parse_react_json(resp.content)   # {"tool":..,"args":..} or {"answer":..}

    accumulate(resp.usage)
    if not tool_calls:
        return AgentResult(answer=resp.content, usage=total, trace=trace)

    for call in tool_calls:
        result = await registry.execute(call.name, call.args, ctx)   # permission-checked
        messages.append(tool_result_message(call, result))           # incl. errors
        trace.append(call.name, call.args, result)

return AgentResult(answer=fallback_summary, ...)   # hit step limit
```

### Behaviors

1. **Two code paths, one interface.** Native and ReAct both produce a `tool_calls` list;
   the loop body is identical. The only branch is how tool calls are obtained.
2. **Tool errors feed back, don't crash.** Errors (incl. `PermissionError`) become `TOOL`
   messages the model sees, so it can recover or apologize. No stack traces to the user.
3. **`max_steps` guard.** On exhaustion, return a graceful fallback rather than hang.
4. **History is injected, not stored (slice 1).** Agent stays stateless; the caller decides
   what history to pass. Conversation-memory persistence is a later slice via the same param.
5. **System prompt built from `ctx`.** Injects name/locale/role and: "You have no climate
   data yourself. To answer anything about the user's risk you MUST call a tool. Never
   invent numbers." Backed by the fact the model literally has no data without tools.
6. **Prompt-injection guard (light, slice 1).** Tool/user content wrapped in delimiters;
   system prompt instructs the model to treat it as data, not instructions. Full input
   sanitization is a later security slice; the seam is here.

### Provider failover

A `FallbackProvider` implements `LLMProvider` and walks the configured chain
(e.g. openrouter -> gemini -> ollama) with light per-provider retry/backoff. The agent
sees a single provider and stays oblivious. All-fail returns `AgentResult(error=...)`.

### Public facade vs. class

`framework.ai.agent(provider=..., registry=..., user=...)` is a thin convenience factory
that constructs and returns an `Agent` (the class whose `run()` loop is described above).
Both are valid entry points; the facade is the clean public API, `Agent` is the unit under
test.

## 5. PRANA as Consumer (first slice)

### `get_risk` tool — `prana/ai_tools/risk.py`

```python
def get_risk(*, ctx: UserContext) -> dict:
    lat = ctx.metadata["lat"]; lon = ctx.metadata["lon"]
    system = PRANASystem(
        api_key=OPENWEATHER_API_KEY,
        location_name=ctx.metadata.get("location_name", "Current location"),
        urban_heat_offset=ctx.metadata.get("urban_heat_offset", 3.0),
        openaq_api_key=OPENAQ_API_KEY,
        onboarding_data=ctx.metadata.get("onboarding"),
    )
    result = system.update_all(lat, lon)          # blocking -> registry runs in threadpool
    return {                                        # trimmed, model-friendly subset
        "ccri": result["ccri"], "ccri_band": result["ccri_band"],
        "ndt": result["ndt"], "rds_mid": result["rds"]["rds_mid"],
        "drivers": result["drivers"], "as_of": result["timestamp"],
    }

risk_tool = Tool(
    name="get_risk",
    description="Get the user's current compound climate risk (heat+pollution+sleep). "
                "Call this whenever the user asks about their risk, heat, air, or sleep.",
    parameters={"type": "object", "properties": {}, "required": []},   # ctx supplies identity
    fn=get_risk,
    required_permission=None,
)
```

Identity (`lat/lon`) comes from `ctx`, never from LLM-supplied args — the model cannot
query another user's location even under prompt injection. This is the authorization model.

> Note: the exact keys returned by `PRANASystem.update_all` must be confirmed against the
> real implementation during build; the subset above is the intended shape and may need
> remapping.

### WhatsApp webhook — `prana/bot/whatsapp_webhook.py`

```
GET  /webhook/whatsapp   -> verify (hub.challenge) using WHATSAPP_VERIFY_TOKEN
POST /webhook/whatsapp:
    verify X-Hub-Signature-256 (WHATSAPP_APP_SECRET)   # reject forged calls
    parse sender phone + text
    user = await user_repo.get_by_phone(phone)
    if not user: reply onboarding prompt; return
    agent = framework.ai.agent(provider=cfg, registry=registry, user=user)
    result = await agent.run(text, ctx=user)
    await messaging.send(channel="whatsapp", recipient=phone, body=result.answer)
    return 200
```

### Bootstrap — `prana/bot/bootstrap.py`

```python
registry = ToolRegistry(); registry.register(risk_tool)
provider = build_provider_from_settings()          # fallback chain
messaging = MessagingRegistry(); messaging.add(WhatsAppChannel(...))
user_repo = SQLiteUserRepository(DATABASE_URL)
```

### SQLite `users` table (minimal)

`user_id, phone, location_name, lat, lon, urban_heat_offset, onboarding_json, role,
locale, created_at`. The `UserRepository` maps a row <-> `UserContext` (engine-specific
fields go in `metadata`).

### Scope honesty

- No onboarding flow yet — unknown phone gets a static "reply START to set up" message.
- Live WhatsApp needs Meta credentials; the full flow is testable via `MockChannel` +
  simulated webhook payloads without a Meta account.

## 6. Configuration

`framework/config/settings.py` (pydantic-settings, env-driven), reads the **same env vars
PRANA already uses** so the OpenRouter/Ollama path needs no new secrets:

```python
class FrameworkSettings(BaseSettings):
    llm_providers: list[str] = ["openrouter", "ollama"]   # fallback chain order
    openrouter_api_key: str = ""; openrouter_model: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"; ollama_model: str = ""
    gemini_api_key: str = ""; gemini_model: str = "gemini-2.0-flash"
    agent_max_steps: int = 5
    agent_temperature: float = 0.2
    whatsapp_access_token: str = ""; whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""; whatsapp_app_secret: str = ""
    smtp_host: str = ""; smtp_port: int = 587; smtp_user: str = ""; smtp_password: str = ""
```

Provider swap = change `llm_providers`. Nothing hardcoded.

## 7. Testing Strategy

Everything runs with zero network calls.

| Layer | How it's tested |
|---|---|
| Providers | `MockProvider` scripted with canned `ChatResponse`s (incl. tool calls). Real adapters get one HTTP-mocked test each (`respx`/`responses`). |
| Agent loop | `MockProvider` + fake tool. Asserts: tool called, result fed back, final answer, `max_steps` guard, permission denial handled, fallback chain switches on error. |
| Tools/permissions | `execute` denies without permission, runs with it, threadpools sync fn, surfaces tool errors as `ToolResult`. |
| Messaging | `MockChannel` captures sends; assert body/recipient/template. |
| Persistence | `InMemoryUserRepository` for logic; one real test against a temp SQLite file. |
| Boundary | import-linter test fails the build if `framework/` imports `prana/`. |
| PRANA slice | `get_risk` with `PRANASystem` mocked; webhook test feeds a fake WhatsApp payload through to `MockChannel` and asserts a reply. Signature-verification test rejects a forged payload. |

Target: the full agent -> tool -> messaging slice is provable in CI without OpenRouter,
Gemini, Ollama, or Meta.

## 8. Out of Scope (named explicitly)

- Q&A over history, sleep check-in collection, proactive alerts/scheduler/events
  (later slices; seams left: `history` param, more tools, an event bus).
- RAG, vector DBs, long-term/semantic memory.
- Telegram/Slack/SMS/push; OAuth2/JWT (phone-from-webhook is slice-1 identity).
- Full monitoring/analytics dashboards; CLI.
- Onboarding conversation flow (static fallback only).
- Migrating/deleting `backend/llm.py` — happens after the new path is green.

## 9. Estimated Effort

- Build to a green, mock-tested, end-to-end slice: ~4-5 focused working sessions
  (~one full focused day of active build; ~a week of calendar time across review checkpoints).
- Gated externally (not build time): live WhatsApp needs Meta credentials + public HTTPS
  webhook; live LLM calls need OpenRouter/Gemini keys. All testable via mocks meanwhile.
