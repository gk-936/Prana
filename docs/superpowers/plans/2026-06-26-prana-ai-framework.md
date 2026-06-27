# PRANA AI Backend Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic, mock-testable `framework/` package (LLM providers, agent, tools, messaging, user context, persistence) and wire PRANA to it so a user can ask "why is my risk high?" over WhatsApp and get a plain-language, tool-grounded answer.

**Architecture:** Protocol-first hexagonal. Every layer is a `typing.Protocol`; concrete adapters implement it; the agent depends only on Protocols. Config selects implementations at startup. PRANA is a *consumer* — it registers a `get_risk` tool wrapping the existing `PRANASystem` and exposes a WhatsApp webhook. The LLM never touches the engine or DB directly; only registered tools do.

**Tech Stack:** Python 3.9, pydantic v2, pydantic-settings, FastAPI, pytest, respx (HTTP mocking), import-linter (boundary enforcement).

## Global Constraints

- **Python 3.9.13** — NO `StrEnum` (3.11+), NO `match` statements. Use `class Role(str, Enum)`. Use `from __future__ import annotations` at the top of every framework file so `X | None` annotations work.
- **`framework/` must NOT import from `prana/` or `backend/`** — enforced by import-linter (Task 14).
- **All framework tests run with zero network calls** — use `MockProvider`, `MockChannel`, `respx` for adapter HTTP tests.
- **pydantic v2 only** (installed: 2.8.2). Use `BaseModel`, `model_config`, `field_validator`. NOT v1 `class Config`.
- **TDD throughout** — failing test first, minimal impl, green, commit.
- Existing `prana/` scoring engine and `backend/llm.py` are NOT modified until Task 16 (cleanup). Leave them working.
- New deps to add to `pyproject.toml` `[project.dependencies]`: `pydantic>=2`, `pydantic-settings>=2`. To `[project.optional-dependencies].dev`: `respx>=0.20`, `import-linter>=2`.
- Real `PRANASystem.update_all(lat, lon)` returns a dict with these confirmed keys (use these EXACT names in the get_risk tool): `ccri` (float), `risk_level` (str band name e.g. "HIGH"), `ndt` (float), `rds` (dict with `rds_low`/`rds_mid`/`rds_high`/`consecutive_nights`), `timestamp` (datetime), `alert_message` (str), `summary` (dict), `components` (dict). There is NO `ccri_band` or `drivers` key.

---

## File Structure

```
framework/__init__.py                 # version, public facade exports
framework/errors.py                   # exception hierarchy
framework/ai/__init__.py
framework/ai/base.py                  # Role, ToolCall, Message, Usage, ChatResponse, LLMProvider Protocol, ToolSchema
framework/ai/mock.py                  # MockProvider
framework/ai/openrouter.py            # OpenRouterProvider
framework/ai/ollama.py                # OllamaProvider
framework/ai/gemini.py                # GeminiProvider
framework/ai/fallback.py              # FallbackProvider
framework/ai/factory.py               # build_provider(settings)
framework/tools/__init__.py
framework/tools/permissions.py        # PermissionDeniedError, check_permission
framework/tools/base.py               # Tool, ToolResult, ToolRegistry
framework/context/__init__.py
framework/context/user.py             # UserContext
framework/agent/__init__.py
framework/agent/result.py             # AgentResult, TraceEntry
framework/agent/react.py              # ReAct prompt builder + parser
framework/agent/base.py               # Agent
framework/messaging/__init__.py
framework/messaging/base.py           # OutboundMessage, DeliveryResult, MessageChannel Protocol
framework/messaging/mock.py           # MockChannel
framework/messaging/whatsapp.py       # WhatsAppChannel
framework/messaging/email.py          # EmailChannel
framework/messaging/webhook.py        # WebhookChannel
framework/messaging/registry.py       # MessagingRegistry
framework/persistence/__init__.py
framework/persistence/base.py         # UserRepository Protocol
framework/persistence/memory.py       # InMemoryUserRepository
framework/persistence/sqlite.py       # SQLiteUserRepository
framework/config/__init__.py
framework/config/settings.py          # FrameworkSettings

prana/ai_tools/__init__.py
prana/ai_tools/risk.py                # get_risk tool
prana/bot/__init__.py
prana/bot/bootstrap.py                # wires registry/provider/messaging/repo
prana/bot/whatsapp_webhook.py         # FastAPI router

tests/framework/...                   # mirrors framework/ structure
tests/prana/test_risk_tool.py
tests/prana/test_whatsapp_webhook.py
.importlinter                         # boundary contract
```

---

### Task 1: Dependencies & package skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `framework/__init__.py`, `framework/errors.py`
- Test: `tests/framework/test_errors.py`

**Interfaces:**
- Produces: `framework.errors.FrameworkError`, `ProviderError`, `ToolError`, `PermissionDeniedError`, `MessagingError`, `ConfigError` (all subclass `FrameworkError`).

- [ ] **Step 1: Add deps and package config to `pyproject.toml`**

In `[project].dependencies` add (keep existing): `"pydantic>=2"`, `"pydantic-settings>=2"`.
In `[project.optional-dependencies].dev` change to: `dev = ["pytest>=7.4.0", "respx>=0.20", "import-linter>=2"]`.
In `[tool.setuptools]` change `packages` to: `packages = ["prana", "backend", "framework"]`.

- [ ] **Step 2: Write failing test for the error hierarchy**

```python
# tests/framework/test_errors.py
import pytest
from framework.errors import (
    FrameworkError, ProviderError, ToolError,
    PermissionDeniedError, MessagingError, ConfigError,
)

@pytest.mark.parametrize("exc", [
    ProviderError, ToolError, PermissionDeniedError, MessagingError, ConfigError,
])
def test_all_errors_subclass_framework_error(exc):
    assert issubclass(exc, FrameworkError)
    with pytest.raises(FrameworkError):
        raise exc("boom")
```

- [ ] **Step 3: Run test, verify it fails**

Run: `python -m pytest tests/framework/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'framework.errors'`

- [ ] **Step 4: Implement**

```python
# framework/__init__.py
"""PRANA AI backend framework — generic, provider-independent."""
__version__ = "0.1.0"
```

```python
# framework/errors.py
from __future__ import annotations


class FrameworkError(Exception):
    """Base class for all framework errors."""


class ProviderError(FrameworkError):
    """An LLM provider call failed."""


class ToolError(FrameworkError):
    """A tool failed to execute."""


class PermissionDeniedError(FrameworkError):
    """The user lacks permission to run a tool."""


class MessagingError(FrameworkError):
    """A messaging channel failed to deliver."""


class ConfigError(FrameworkError):
    """Invalid or missing configuration."""
```

Also create empty `tests/framework/__init__.py`.

- [ ] **Step 5: Run test, verify pass**

Run: `python -m pytest tests/framework/test_errors.py -v`
Expected: PASS (5 params)

- [ ] **Step 6: Install dev deps and commit**

```bash
pip install -e ".[dev]"
git add pyproject.toml framework/__init__.py framework/errors.py tests/framework/
git commit -m "feat(framework): package skeleton + error hierarchy"
```

---

### Task 2: AI core types & LLMProvider Protocol

**Files:**
- Create: `framework/ai/__init__.py`, `framework/ai/base.py`
- Test: `tests/framework/ai/test_base.py`

**Interfaces:**
- Produces:
  - `Role(str, Enum)` with `SYSTEM`, `USER`, `ASSISTANT`, `TOOL`.
  - `ToolCall` dataclass: `id: str`, `name: str`, `arguments: dict`.
  - `Message` dataclass: `role: Role`, `content: str`, `tool_calls: list[ToolCall] | None = None`, `tool_call_id: str | None = None`.
  - `Usage` dataclass: `prompt_tokens: int = 0`, `completion_tokens: int = 0`, `cost_usd: float | None = None`; method `__add__` returns summed `Usage` (cost None unless both set).
  - `ChatResponse` dataclass: `content: str | None`, `tool_calls: list[ToolCall]`, `usage: Usage`, `raw: dict`.
  - `ToolSchema = dict` (type alias for an OpenAI-style function schema).
  - `LLMProvider(Protocol)`: attrs `name: str`, `supports_native_tools: bool`; method `chat(self, messages: list[Message], *, tools: list[ToolSchema] | None = None, temperature: float = 0.2) -> ChatResponse`.

- [ ] **Step 1: Write failing test**

```python
# tests/framework/ai/test_base.py
from framework.ai.base import Role, ToolCall, Message, Usage, ChatResponse


def test_role_values():
    assert Role.USER == "user"
    assert Role.TOOL.value == "tool"


def test_message_defaults():
    m = Message(role=Role.USER, content="hi")
    assert m.tool_calls is None and m.tool_call_id is None


def test_usage_add_sums_tokens():
    a = Usage(prompt_tokens=10, completion_tokens=5, cost_usd=0.01)
    b = Usage(prompt_tokens=3, completion_tokens=2, cost_usd=0.02)
    total = a + b
    assert total.prompt_tokens == 13 and total.completion_tokens == 7
    assert abs(total.cost_usd - 0.03) < 1e-9


def test_usage_add_cost_none_when_either_missing():
    total = Usage(1, 1, None) + Usage(1, 1, 0.5)
    assert total.cost_usd is None


def test_chat_response_holds_tool_calls():
    tc = ToolCall(id="1", name="get_risk", arguments={})
    r = ChatResponse(content=None, tool_calls=[tc], usage=Usage(), raw={})
    assert r.tool_calls[0].name == "get_risk"
```

- [ ] **Step 2: Run test, verify fails**

Run: `python -m pytest tests/framework/ai/test_base.py -v`
Expected: FAIL — `No module named 'framework.ai'`

- [ ] **Step 3: Implement**

```python
# framework/ai/__init__.py
```

```python
# framework/ai/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: Role
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None

    def __add__(self, other: "Usage") -> "Usage":
        cost = (
            self.cost_usd + other.cost_usd
            if self.cost_usd is not None and other.cost_usd is not None
            else None
        )
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cost_usd=cost,
        )


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    raw: dict = field(default_factory=dict)


ToolSchema = dict


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    supports_native_tools: bool

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
    ) -> ChatResponse:
        ...
```

Create empty `tests/framework/ai/__init__.py`.

- [ ] **Step 4: Run test, verify pass**

Run: `python -m pytest tests/framework/ai/test_base.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add framework/ai/ tests/framework/ai/
git commit -m "feat(framework): AI core types and LLMProvider protocol"
```

---

### Task 3: MockProvider

**Files:**
- Create: `framework/ai/mock.py`
- Test: `tests/framework/ai/test_mock.py`

**Interfaces:**
- Consumes: `framework.ai.base` types.
- Produces: `MockProvider(responses: list[ChatResponse], supports_native_tools: bool = True)`. Each `chat()` call pops the next scripted response in order; records calls in `.calls: list[dict]` (each `{"messages":..., "tools":..., "temperature":...}`). Raises `ProviderError` if scripted to via `MockProvider(error=...)`. `name = "mock"`.

- [ ] **Step 1: Write failing test**

```python
# tests/framework/ai/test_mock.py
import pytest
from framework.ai.base import ChatResponse, Usage, Role, Message, ToolCall
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
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/ai/test_mock.py -v`
Expected: FAIL — `No module named 'framework.ai.mock'`

- [ ] **Step 3: Implement**

```python
# framework/ai/mock.py
from __future__ import annotations

from framework.ai.base import ChatResponse, Message, ToolSchema, Usage
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
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/framework/ai/test_mock.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add framework/ai/mock.py tests/framework/ai/test_mock.py
git commit -m "feat(framework): MockProvider for tests"
```

---

### Task 4: UserContext

**Files:**
- Create: `framework/context/__init__.py`, `framework/context/user.py`
- Test: `tests/framework/context/test_user.py`

**Interfaces:**
- Produces: `UserContext(BaseModel)` with fields per spec §3; method `has_permission(self, perm: str) -> bool` returns `True` if `perm in self.permissions` OR `role == "admin"`.

- [ ] **Step 1: Write failing test**

```python
# tests/framework/context/test_user.py
from framework.context.user import UserContext


def test_minimal_user_defaults():
    u = UserContext(user_id="u1")
    assert u.role == "user" and u.locale == "en" and u.timezone == "UTC"
    assert u.permissions == frozenset()


def test_has_permission_explicit():
    u = UserContext(user_id="u1", permissions=frozenset({"read_orders"}))
    assert u.has_permission("read_orders")
    assert not u.has_permission("delete_users")


def test_admin_has_all_permissions():
    u = UserContext(user_id="a1", role="admin")
    assert u.has_permission("anything")


def test_metadata_holds_app_fields():
    u = UserContext(user_id="u1", metadata={"lat": 13.08, "lon": 80.27})
    assert u.metadata["lat"] == 13.08
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/context/test_user.py -v`
Expected: FAIL — `No module named 'framework.context'`

- [ ] **Step 3: Implement**

```python
# framework/context/__init__.py
```

```python
# framework/context/user.py
from __future__ import annotations

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    user_id: str
    organization_id: str | None = None
    username: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str = "user"
    permissions: frozenset[str] = Field(default_factory=frozenset)
    locale: str = "en"
    timezone: str = "UTC"
    preferences: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    def has_permission(self, perm: str) -> bool:
        return self.role == "admin" or perm in self.permissions
```

Create empty `tests/framework/context/__init__.py`.

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/framework/context/test_user.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add framework/context/ tests/framework/context/
git commit -m "feat(framework): UserContext with permission check"
```

---

### Task 5: Tool, ToolResult, permissions

**Files:**
- Create: `framework/tools/__init__.py`, `framework/tools/permissions.py`, `framework/tools/base.py` (Tool + ToolResult only; registry in Task 6)
- Test: `tests/framework/tools/test_permissions.py`

**Interfaces:**
- Produces:
  - `Tool` dataclass: `name: str`, `description: str`, `parameters: dict`, `fn: Callable`, `required_permission: str | None = None`. Method `to_schema() -> dict` returns `{"type":"function","function":{"name","description","parameters"}}`.
  - `ToolResult` dataclass: `ok: bool`, `data: object = None`, `error: str | None = None`.
  - `check_permission(tool: Tool, ctx: UserContext) -> None` raises `PermissionDeniedError` if `tool.required_permission` set and `not ctx.has_permission(...)`.

- [ ] **Step 1: Write failing test**

```python
# tests/framework/tools/test_permissions.py
import pytest
from framework.tools.base import Tool, ToolResult
from framework.tools.permissions import check_permission
from framework.context.user import UserContext
from framework.errors import PermissionDeniedError


def _tool(perm=None):
    return Tool(name="t", description="d", parameters={}, fn=lambda **k: 1,
                required_permission=perm)


def test_no_required_permission_passes():
    check_permission(_tool(), UserContext(user_id="u"))  # no raise


def test_missing_permission_raises():
    with pytest.raises(PermissionDeniedError):
        check_permission(_tool("admin_only"), UserContext(user_id="u"))


def test_with_permission_passes():
    ctx = UserContext(user_id="u", permissions=frozenset({"admin_only"}))
    check_permission(_tool("admin_only"), ctx)  # no raise


def test_tool_to_schema_shape():
    t = Tool(name="get_risk", description="risk", parameters={"type": "object"},
             fn=lambda **k: 1)
    s = t.to_schema()
    assert s["type"] == "function"
    assert s["function"]["name"] == "get_risk"
    assert s["function"]["parameters"] == {"type": "object"}
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/tools/test_permissions.py -v`
Expected: FAIL — `No module named 'framework.tools'`

- [ ] **Step 3: Implement**

```python
# framework/tools/__init__.py
```

```python
# framework/tools/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Any]
    required_permission: str | None = None

    def to_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
```

```python
# framework/tools/permissions.py
from __future__ import annotations

from framework.context.user import UserContext
from framework.errors import PermissionDeniedError
from framework.tools.base import Tool


def check_permission(tool: Tool, ctx: UserContext) -> None:
    if tool.required_permission and not ctx.has_permission(tool.required_permission):
        raise PermissionDeniedError(
            f"User {ctx.user_id} lacks permission '{tool.required_permission}' "
            f"for tool '{tool.name}'"
        )
```

Create empty `tests/framework/tools/__init__.py`.

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/framework/tools/test_permissions.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add framework/tools/ tests/framework/tools/
git commit -m "feat(framework): Tool, ToolResult, permission check"
```

---

### Task 6: ToolRegistry (with sync/async execution + permission gate)

**Files:**
- Modify: `framework/tools/base.py` (add `ToolRegistry`)
- Test: `tests/framework/tools/test_registry.py`

**Interfaces:**
- Consumes: `Tool`, `ToolResult`, `check_permission`, `UserContext`.
- Produces: `ToolRegistry()` with:
  - `register(tool: Tool) -> None` (raises `ToolError` on duplicate name)
  - `get(name: str) -> Tool` (raises `ToolError` if missing)
  - `schemas() -> list[dict]` (each `tool.to_schema()`)
  - `async execute(name: str, args: dict, ctx: UserContext) -> ToolResult` — checks permission FIRST; runs async `fn` via `await`, sync `fn` via `asyncio.to_thread`; always passes `ctx=ctx` plus `**args`; returns `ToolResult(ok=False, error=...)` on `PermissionDeniedError` or any exception (never raises out).

- [ ] **Step 1: Write failing test**

```python
# tests/framework/tools/test_registry.py
import asyncio
import pytest
from framework.tools.base import Tool, ToolRegistry, ToolResult
from framework.context.user import UserContext
from framework.errors import ToolError


def _reg(tool):
    r = ToolRegistry(); r.register(tool); return r


def test_register_duplicate_raises():
    t = Tool("a", "d", {}, fn=lambda **k: 1)
    r = ToolRegistry(); r.register(t)
    with pytest.raises(ToolError):
        r.register(t)


def test_get_missing_raises():
    with pytest.raises(ToolError):
        ToolRegistry().get("nope")


def test_schemas_returns_function_schemas():
    r = _reg(Tool("a", "d", {"type": "object"}, fn=lambda **k: 1))
    assert r.schemas()[0]["function"]["name"] == "a"


def test_execute_sync_tool_passes_ctx_and_args():
    def fn(*, ctx, x):
        return {"who": ctx.user_id, "x2": x * 2}
    r = _reg(Tool("a", "d", {}, fn=fn))
    res = asyncio.run(r.execute("a", {"x": 5}, UserContext(user_id="u1")))
    assert res.ok and res.data == {"who": "u1", "x2": 10}


def test_execute_async_tool():
    async def fn(*, ctx):
        return "async-ok"
    r = _reg(Tool("a", "d", {}, fn=fn))
    res = asyncio.run(r.execute("a", {}, UserContext(user_id="u1")))
    assert res.ok and res.data == "async-ok"


def test_execute_permission_denied_returns_error_result():
    r = _reg(Tool("a", "d", {}, fn=lambda **k: 1, required_permission="admin"))
    res = asyncio.run(r.execute("a", {}, UserContext(user_id="u1")))
    assert not res.ok and "permission" in res.error.lower()


def test_execute_tool_exception_returns_error_result():
    def boom(**k):
        raise ValueError("kaboom")
    r = _reg(Tool("a", "d", {}, fn=boom))
    res = asyncio.run(r.execute("a", {}, UserContext(user_id="u1")))
    assert not res.ok and "kaboom" in res.error
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/tools/test_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'ToolRegistry'`

- [ ] **Step 3: Implement (append to `framework/tools/base.py`)**

```python
# append to framework/tools/base.py
import asyncio
import inspect

from framework.context.user import UserContext
from framework.errors import PermissionDeniedError, ToolError
from framework.tools.permissions import check_permission


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ToolError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"Unknown tool '{name}'")
        return self._tools[name]

    def schemas(self) -> list[dict]:
        return [t.to_schema() for t in self._tools.values()]

    async def execute(self, name: str, args: dict, ctx: UserContext) -> ToolResult:
        try:
            tool = self.get(name)
            check_permission(tool, ctx)
            if inspect.iscoroutinefunction(tool.fn):
                data = await tool.fn(ctx=ctx, **args)
            else:
                data = await asyncio.to_thread(lambda: tool.fn(ctx=ctx, **args))
            return ToolResult(ok=True, data=data)
        except PermissionDeniedError as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - surface to model, never crash loop
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
```

Note: the top-of-file `from __future__ import annotations` already added in Task 5 stays; move the new `import asyncio`/`import inspect` to the top import block during implementation (don't leave imports mid-file).

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/framework/tools/test_registry.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add framework/tools/base.py tests/framework/tools/test_registry.py
git commit -m "feat(framework): ToolRegistry with permission gate and sync/async execution"
```

---

### Task 7: ReAct prompt builder + parser (fallback path)

**Files:**
- Create: `framework/agent/__init__.py`, `framework/agent/react.py`
- Test: `tests/framework/agent/test_react.py`

**Interfaces:**
- Consumes: `Message`, `Role`, `ToolCall`, tool schemas.
- Produces:
  - `build_react_messages(messages: list[Message], schemas: list[dict]) -> list[Message]` — returns messages with an appended/prepended system instruction telling the model to reply with ONLY a JSON object: either `{"tool": "<name>", "args": {...}}` or `{"answer": "<text>"}`, listing the available tools and their schemas.
  - `parse_react_response(content: str) -> tuple[list[ToolCall], str | None]` — returns `([ToolCall], None)` if a tool call is parsed, or `([], answer_text)` if an answer. Tolerates code fences (```json ... ```) and surrounding prose; if no JSON parses, treats the whole content as a plain answer.

- [ ] **Step 1: Write failing test**

```python
# tests/framework/agent/test_react.py
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
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/agent/test_react.py -v`
Expected: FAIL — `No module named 'framework.agent'`

- [ ] **Step 3: Implement**

```python
# framework/agent/__init__.py
```

```python
# framework/agent/react.py
from __future__ import annotations

import json
import re
import uuid

from framework.ai.base import Message, Role, ToolCall

_INSTRUCTION = (
    "You can call tools. Reply with ONLY a single JSON object and nothing else.\n"
    'To call a tool: {{"tool": "<tool_name>", "args": {{<json args>}}}}\n'
    'To answer the user: {{"answer": "<your reply>"}}\n'
    "Available tools:\n{tools}"
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_react_messages(messages: list[Message], schemas: list[dict]) -> list[Message]:
    tool_lines = []
    for s in schemas:
        fn = s["function"]
        tool_lines.append(
            f"- {fn['name']}: {fn['description']} params={json.dumps(fn['parameters'])}"
        )
    instruction = _INSTRUCTION.format(tools="\n".join(tool_lines) or "(none)")
    return list(messages) + [Message(role=Role.SYSTEM, content=instruction)]


def _extract_json(content: str) -> dict | None:
    for pattern in (_FENCE_RE, _OBJ_RE):
        m = pattern.search(content)
        if m:
            try:
                return json.loads(m.group(1) if pattern is _FENCE_RE else m.group(0))
            except json.JSONDecodeError:
                continue
    return None


def parse_react_response(content: str) -> tuple[list[ToolCall], str | None]:
    obj = _extract_json(content)
    if isinstance(obj, dict) and "tool" in obj:
        return (
            [ToolCall(id=str(uuid.uuid4()), name=obj["tool"], arguments=obj.get("args", {}))],
            None,
        )
    if isinstance(obj, dict) and "answer" in obj:
        return [], str(obj["answer"])
    return [], content
```

Create empty `tests/framework/agent/__init__.py`.

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/framework/agent/test_react.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add framework/agent/__init__.py framework/agent/react.py tests/framework/agent/
git commit -m "feat(framework): ReAct prompt builder and parser for fallback tool-calling"
```

---

### Task 8: AgentResult + Agent loop

**Files:**
- Create: `framework/agent/result.py`, `framework/agent/base.py`
- Test: `tests/framework/agent/test_agent.py`

**Interfaces:**
- Consumes: `LLMProvider`, `ToolRegistry`, `UserContext`, `Message`/`Role`/`ToolCall`/`Usage`, ReAct helpers.
- Produces:
  - `TraceEntry` dataclass: `tool: str`, `args: dict`, `ok: bool`, `error: str | None`.
  - `AgentResult` dataclass: `answer: str | None`, `usage: Usage`, `trace: list[TraceEntry]`, `error: str | None = None`, `steps: int = 0`.
  - `Agent(provider, registry, *, system_prompt_fn=None, max_steps=5, temperature=0.2)`.
  - `async Agent.run(user_message: str, ctx: UserContext, history: list[Message] | None = None) -> AgentResult`.
  - Default system prompt: includes user name/locale and "You have no data of your own; to answer anything about the user you MUST call a tool; never invent numbers."

- [ ] **Step 1: Write failing test**

```python
# tests/framework/agent/test_agent.py
import asyncio
from framework.agent.base import Agent
from framework.agent.result import AgentResult
from framework.ai.base import ChatResponse, ToolCall, Usage, Role, Message
from framework.ai.mock import MockProvider
from framework.tools.base import Tool, ToolRegistry
from framework.context.user import UserContext


def _registry():
    r = ToolRegistry()
    r.register(Tool("get_risk", "risk", {"type": "object", "properties": {}},
                    fn=lambda *, ctx: {"ccri": 72, "risk_level": "HIGH"}))
    return r


def _run(agent, msg):
    return asyncio.run(agent.run(msg, UserContext(user_id="u1")))


def test_native_tool_call_then_answer():
    provider = MockProvider(responses=[
        ChatResponse(content=None, tool_calls=[ToolCall("1", "get_risk", {})], usage=Usage(5, 5, 0.01)),
        ChatResponse(content="Your risk is HIGH (72).", usage=Usage(8, 4, 0.01)),
    ], supports_native_tools=True)
    res = _run(Agent(provider, _registry()), "why is my risk high?")
    assert res.answer == "Your risk is HIGH (72)."
    assert res.trace[0].tool == "get_risk" and res.trace[0].ok
    assert res.usage.prompt_tokens == 13 and abs(res.usage.cost_usd - 0.02) < 1e-9


def test_direct_answer_no_tool():
    provider = MockProvider(responses=[ChatResponse(content="Hello!", usage=Usage())])
    res = _run(Agent(provider, _registry()), "hi")
    assert res.answer == "Hello!" and res.trace == []


def test_react_fallback_path():
    provider = MockProvider(responses=[
        ChatResponse(content='{"tool":"get_risk","args":{}}', usage=Usage()),
        ChatResponse(content='{"answer":"Risk HIGH"}', usage=Usage()),
    ], supports_native_tools=False)
    res = _run(Agent(provider, _registry()), "risk?")
    assert res.answer == "Risk HIGH"
    assert res.trace[0].tool == "get_risk"
    # fallback path must NOT pass native tools to provider
    assert provider.calls[0]["tools"] is None


def test_max_steps_guard():
    # provider always asks for a tool, never answers
    loop = [ChatResponse(content=None, tool_calls=[ToolCall("1", "get_risk", {})], usage=Usage())
            for _ in range(10)]
    provider = MockProvider(responses=loop)
    res = _run(Agent(provider, _registry(), max_steps=3), "loop")
    assert res.steps == 3
    assert res.answer is not None  # graceful fallback string


def test_permission_error_feeds_back_not_crash():
    r = ToolRegistry()
    r.register(Tool("admin_tool", "x", {}, fn=lambda *, ctx: 1, required_permission="admin"))
    provider = MockProvider(responses=[
        ChatResponse(content=None, tool_calls=[ToolCall("1", "admin_tool", {})], usage=Usage()),
        ChatResponse(content="You are not authorized.", usage=Usage()),
    ])
    res = _run(Agent(provider, r), "do admin thing")
    assert res.answer == "You are not authorized."
    assert not res.trace[0].ok
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/agent/test_agent.py -v`
Expected: FAIL — `No module named 'framework.agent.result'`

- [ ] **Step 3: Implement**

```python
# framework/agent/result.py
from __future__ import annotations

from dataclasses import dataclass, field

from framework.ai.base import Usage


@dataclass
class TraceEntry:
    tool: str
    args: dict
    ok: bool
    error: str | None = None


@dataclass
class AgentResult:
    answer: str | None
    usage: Usage = field(default_factory=Usage)
    trace: list[TraceEntry] = field(default_factory=list)
    error: str | None = None
    steps: int = 0
```

```python
# framework/agent/base.py
from __future__ import annotations

import json
from typing import Callable

from framework.agent.react import build_react_messages, parse_react_response
from framework.agent.result import AgentResult, TraceEntry
from framework.ai.base import ChatResponse, LLMProvider, Message, Role, Usage
from framework.context.user import UserContext
from framework.tools.base import ToolRegistry

_DEFAULT_SYSTEM = (
    "You are a helpful assistant for {name} (locale={locale}). "
    "You have no data of your own. To answer anything about the user or their data "
    "you MUST call a tool. Never invent numbers or facts."
)
_FALLBACK_ANSWER = (
    "I'm having trouble completing that request right now. Please try again shortly."
)


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        *,
        system_prompt_fn: Callable[[UserContext], str] | None = None,
        max_steps: int = 5,
        temperature: float = 0.2,
    ):
        self.provider = provider
        self.registry = registry
        self.system_prompt_fn = system_prompt_fn or self._default_system_prompt
        self.max_steps = max_steps
        self.temperature = temperature

    @staticmethod
    def _default_system_prompt(ctx: UserContext) -> str:
        return _DEFAULT_SYSTEM.format(name=ctx.username or "the user", locale=ctx.locale)

    async def run(
        self,
        user_message: str,
        ctx: UserContext,
        history: list[Message] | None = None,
    ) -> AgentResult:
        messages: list[Message] = [
            Message(Role.SYSTEM, self.system_prompt_fn(ctx)),
            *(history or []),
            Message(Role.USER, user_message),
        ]
        total = Usage()
        trace: list[TraceEntry] = []

        for step in range(1, self.max_steps + 1):
            if self.provider.supports_native_tools:
                resp = self.provider.chat(
                    messages, tools=self.registry.schemas(), temperature=self.temperature
                )
                tool_calls = resp.tool_calls
                answer = resp.content
            else:
                react_msgs = build_react_messages(messages, self.registry.schemas())
                resp = self.provider.chat(react_msgs, tools=None, temperature=self.temperature)
                tool_calls, answer = parse_react_response(resp.content or "")

            total = total + resp.usage

            if not tool_calls:
                return AgentResult(answer=answer, usage=total, trace=trace, steps=step)

            messages.append(
                Message(Role.ASSISTANT, resp.content or "", tool_calls=tool_calls)
            )
            for call in tool_calls:
                result = await self.registry.execute(call.name, call.arguments, ctx)
                trace.append(
                    TraceEntry(call.name, call.arguments, result.ok, result.error)
                )
                payload = result.data if result.ok else {"error": result.error}
                messages.append(
                    Message(
                        Role.TOOL,
                        content=f"<tool_result>{json.dumps(payload, default=str)}</tool_result>",
                        tool_call_id=call.id,
                    )
                )

        return AgentResult(
            answer=_FALLBACK_ANSWER, usage=total, trace=trace, steps=self.max_steps
        )
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/framework/agent/test_agent.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add framework/agent/result.py framework/agent/base.py tests/framework/agent/test_agent.py
git commit -m "feat(framework): Agent reasoning loop (native + ReAct, permission-safe, max-steps)"
```

---

### Task 9: Real LLM adapters (OpenRouter, Ollama, Gemini) — HTTP-mocked

**Files:**
- Create: `framework/ai/openrouter.py`, `framework/ai/ollama.py`, `framework/ai/gemini.py`
- Test: `tests/framework/ai/test_adapters.py`

**Interfaces:**
- Consumes: `framework.ai.base` types, `requests`, `respx` (test).
- Produces (each implements `LLMProvider`):
  - `OpenRouterProvider(api_key, model, base_url="https://openrouter.ai/api/v1")`, `supports_native_tools = True`. Posts to `{base_url}/chat/completions`. Parses `choices[0].message.content` and `choices[0].message.tool_calls` (OpenAI shape) into `ChatResponse`; `usage` from response `usage` block.
  - `OllamaProvider(model, base_url="http://127.0.0.1:11434")`, `supports_native_tools = False`. Posts to `{base_url}/api/chat`, `stream=False`. Parses `message.content`.
  - `GeminiProvider(api_key, model="gemini-2.0-flash", base_url="https://generativelanguage.googleapis.com/v1beta")`, `supports_native_tools = True`. Posts to `{base_url}/models/{model}:generateContent?key=...`; parses `candidates[0].content.parts`. (Tool-call parsing for Gemini's `functionCall` parts.)
  - All raise `ProviderError` on HTTP error / missing config, with original error chained.

- [ ] **Step 1: Write failing tests (respx-mocked, no network)**

```python
# tests/framework/ai/test_adapters.py
import httpx
import pytest
import respx
from framework.ai.base import Message, Role
from framework.ai.openrouter import OpenRouterProvider
from framework.ai.ollama import OllamaProvider
from framework.errors import ProviderError


@respx.mock
def test_openrouter_parses_content_and_usage():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "hello", "tool_calls": None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        })
    )
    p = OpenRouterProvider(api_key="k", model="m")
    r = p.chat([Message(Role.USER, "hi")])
    assert r.content == "hello"
    assert r.usage.prompt_tokens == 10 and r.usage.completion_tokens == 3


@respx.mock
def test_openrouter_parses_tool_calls():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": None, "tool_calls": [
                {"id": "c1", "function": {"name": "get_risk", "arguments": "{\"x\": 1}"}}
            ]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })
    )
    r = OpenRouterProvider(api_key="k", model="m").chat([Message(Role.USER, "hi")])
    assert r.tool_calls[0].name == "get_risk" and r.tool_calls[0].arguments == {"x": 1}


@respx.mock
def test_openrouter_http_error_raises_provider_error():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    with pytest.raises(ProviderError):
        OpenRouterProvider(api_key="k", model="m").chat([Message(Role.USER, "hi")])


def test_openrouter_missing_key_raises():
    with pytest.raises(ProviderError):
        OpenRouterProvider(api_key="", model="m").chat([Message(Role.USER, "hi")])


@respx.mock
def test_ollama_parses_content():
    respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "local reply"}})
    )
    r = OllamaProvider(model="llama3").chat([Message(Role.USER, "hi")])
    assert r.content == "local reply" and r.tool_calls == []
```

NOTE: adapters use `requests`; respx mocks `httpx`. To make respx work, adapters MUST use `httpx` (sync `httpx.Client`) instead of `requests`. Add `httpx` to dependencies (it's already a FastAPI/uvicorn transitive dep but add explicitly: `"httpx>=0.27"` in `[project.dependencies]`).

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/ai/test_adapters.py -v`
Expected: FAIL — `No module named 'framework.ai.openrouter'`

- [ ] **Step 3: Implement OpenRouter**

```python
# framework/ai/openrouter.py
from __future__ import annotations

import json

import httpx

from framework.ai.base import ChatResponse, Message, ToolCall, ToolSchema, Usage
from framework.errors import ProviderError


class OpenRouterProvider:
    name = "openrouter"
    supports_native_tools = True

    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://openrouter.ai/api/v1", timeout: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[Message], *, tools: list[ToolSchema] | None = None,
             temperature: float = 0.2) -> ChatResponse:
        if not self.api_key:
            raise ProviderError("OPENROUTER_API_KEY is not configured")
        payload: dict = {
            "model": self.model,
            "messages": [self._encode(m) for m in messages],
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://prana.local",
            "X-Title": "PRANA",
        }
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions",
                              headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenRouter request failed: {exc}") from exc
        return self._decode(resp.json())

    @staticmethod
    def _encode(m: Message) -> dict:
        out: dict = {"role": m.role.value, "content": m.content}
        if m.tool_call_id:
            out["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            out["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in m.tool_calls
            ]
        return out

    @staticmethod
    def _decode(data: dict) -> ChatResponse:
        msg = data["choices"][0]["message"]
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc["function"]
            args = fn.get("arguments") or "{}"
            tool_calls.append(ToolCall(
                id=tc.get("id", ""), name=fn["name"],
                arguments=json.loads(args) if isinstance(args, str) else args,
            ))
        u = data.get("usage") or {}
        return ChatResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
            usage=Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)),
            raw=data,
        )
```

- [ ] **Step 4: Implement Ollama**

```python
# framework/ai/ollama.py
from __future__ import annotations

import httpx

from framework.ai.base import ChatResponse, Message, ToolSchema, Usage
from framework.errors import ProviderError


class OllamaProvider:
    name = "ollama"
    supports_native_tools = False

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434",
                 timeout: float = 60.0):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[Message], *, tools: list[ToolSchema] | None = None,
             temperature: float = 0.2) -> ChatResponse:
        if not self.model:
            raise ProviderError("OLLAMA_MODEL is not configured")
        payload = {
            "model": self.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "options": {"temperature": temperature},
            "stream": False,
        }
        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc
        data = resp.json()
        return ChatResponse(content=data["message"]["content"], usage=Usage(), raw=data)
```

- [ ] **Step 5: Implement Gemini**

```python
# framework/ai/gemini.py
from __future__ import annotations

import httpx

from framework.ai.base import ChatResponse, Message, Role, ToolCall, ToolSchema, Usage
from framework.errors import ProviderError

_ROLE_MAP = {Role.USER: "user", Role.ASSISTANT: "model", Role.SYSTEM: "user", Role.TOOL: "user"}


class GeminiProvider:
    name = "gemini"
    supports_native_tools = True

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash",
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta",
                 timeout: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[Message], *, tools: list[ToolSchema] | None = None,
             temperature: float = 0.2) -> ChatResponse:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is not configured")
        contents = [
            {"role": _ROLE_MAP[m.role], "parts": [{"text": m.content}]} for m in messages
        ]
        payload: dict = {"contents": contents, "generationConfig": {"temperature": temperature}}
        if tools:
            payload["tools"] = [{"function_declarations": [t["function"] for t in tools]}]
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        try:
            resp = httpx.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc
        return self._decode(resp.json())

    @staticmethod
    def _decode(data: dict) -> ChatResponse:
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text_parts, tool_calls = [], []
        for i, part in enumerate(parts):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(ToolCall(id=str(i), name=fc["name"], arguments=fc.get("args", {})))
        return ChatResponse(
            content="".join(text_parts) or None, tool_calls=tool_calls, usage=Usage(), raw=data
        )
```

Add `"httpx>=0.27"` to `[project.dependencies]` in `pyproject.toml`.

- [ ] **Step 6: Run, verify pass**

Run: `python -m pytest tests/framework/ai/test_adapters.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add framework/ai/openrouter.py framework/ai/ollama.py framework/ai/gemini.py tests/framework/ai/test_adapters.py pyproject.toml
git commit -m "feat(framework): OpenRouter, Ollama, Gemini providers (httpx, mock-tested)"
```

---

### Task 10: FallbackProvider

**Files:**
- Create: `framework/ai/fallback.py`
- Test: `tests/framework/ai/test_fallback.py`

**Interfaces:**
- Consumes: `LLMProvider`, `ProviderError`.
- Produces: `FallbackProvider(providers: list[LLMProvider])` implementing `LLMProvider`. `name = "fallback"`. `supports_native_tools` = that of the FIRST provider (the loop re-evaluates per provider internally, but agent reads this attr; document that mixed-capability chains use the first provider's flag and each provider still gets tools only if it itself supports them — to keep it simple, `chat()` passes `tools` through unchanged and relies on providers ignoring unknown args). On `chat()`, try each provider in order; on `ProviderError` (or any `Exception`), try the next; if all fail, raise `ProviderError` listing all failures. Records nothing else.

  Simplification note: since `tools` is only meaningfully passed when `supports_native_tools` is True, and the Agent decides that from `FallbackProvider.supports_native_tools` (first provider), keep all providers in a chain homogeneous in tool support where possible. Test covers the failover behavior, not mixed capability.

- [ ] **Step 1: Write failing test**

```python
# tests/framework/ai/test_fallback.py
import pytest
from framework.ai.base import ChatResponse, Message, Role, Usage
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
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/ai/test_fallback.py -v`
Expected: FAIL — `No module named 'framework.ai.fallback'`

- [ ] **Step 3: Implement**

```python
# framework/ai/fallback.py
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
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/framework/ai/test_fallback.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add framework/ai/fallback.py tests/framework/ai/test_fallback.py
git commit -m "feat(framework): FallbackProvider chain"
```

---

### Task 11: Settings + provider factory + public facade

**Files:**
- Create: `framework/config/__init__.py`, `framework/config/settings.py`, `framework/ai/factory.py`
- Modify: `framework/__init__.py` (add facade)
- Test: `tests/framework/config/test_settings.py`, `tests/framework/ai/test_factory.py`

**Interfaces:**
- Produces:
  - `FrameworkSettings(BaseSettings)` per spec §6, env-driven. `llm_providers: list[str]` default `["openrouter", "ollama"]`; reads env var `LLM_PROVIDERS` as comma-separated.
  - `build_provider(settings: FrameworkSettings) -> LLMProvider` — constructs each named provider, wraps in `FallbackProvider` if >1; raises `ConfigError` for unknown provider name.
  - `framework.agent(provider, registry, user=None, **kw) -> Agent` facade (in `framework/__init__.py`): thin factory returning `Agent(provider, registry, **kw)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/framework/config/test_settings.py
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
```

```python
# tests/framework/ai/test_factory.py
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
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/config/ tests/framework/ai/test_factory.py -v`
Expected: FAIL — `No module named 'framework.config.settings'`

- [ ] **Step 3: Implement settings**

```python
# framework/config/__init__.py
```

```python
# framework/config/settings.py
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FrameworkSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_providers: list[str] = ["openrouter", "ollama"]
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    agent_max_steps: int = 5
    agent_temperature: float = 0.2
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    @field_validator("llm_providers", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v
```

- [ ] **Step 4: Implement factory**

```python
# framework/ai/factory.py
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
```

- [ ] **Step 5: Add facade to `framework/__init__.py`**

```python
# framework/__init__.py
"""PRANA AI backend framework — generic, provider-independent."""
from framework.agent.base import Agent

__version__ = "0.1.0"


def agent(provider, registry, *, user=None, **kw) -> Agent:
    """Public facade: construct an Agent. `user` accepted for API symmetry; the
    UserContext is passed per-call to Agent.run()."""
    return Agent(provider, registry, **kw)
```

- [ ] **Step 6: Run, verify pass**

Run: `python -m pytest tests/framework/config/ tests/framework/ai/test_factory.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add framework/config/ framework/ai/factory.py framework/__init__.py tests/framework/config/ tests/framework/ai/test_factory.py
git commit -m "feat(framework): settings, provider factory, public agent facade"
```

---

### Task 12: Messaging — base, MockChannel, registry, WhatsApp/Email/Webhook

**Files:**
- Create: `framework/messaging/__init__.py`, `framework/messaging/base.py`, `framework/messaging/mock.py`, `framework/messaging/registry.py`, `framework/messaging/whatsapp.py`, `framework/messaging/email.py`, `framework/messaging/webhook.py`
- Test: `tests/framework/messaging/test_messaging.py`, `tests/framework/messaging/test_whatsapp.py`

**Interfaces:**
- Produces:
  - `OutboundMessage` dataclass: `recipient: str`, `body: str`, `template: str | None = None`, `data: dict = {}`.
  - `DeliveryResult` dataclass: `ok: bool`, `provider_message_id: str | None = None`, `error: str | None = None`.
  - `MessageChannel(Protocol)`: `name: str`; `async send(msg) -> DeliveryResult`.
  - `MockChannel(name="mock")`: records `.sent: list[OutboundMessage]`, returns `DeliveryResult(ok=True, provider_message_id="mock-<n>")`.
  - `MessagingRegistry`: `add(channel)`, `async send(*, channel: str, recipient: str, body: str, template=None, data=None) -> DeliveryResult` (raises `MessagingError` for unknown channel).
  - `WhatsAppChannel(access_token, phone_number_id, base_url="https://graph.facebook.com/v20.0")`, `name="whatsapp"`: POSTs text message to Graph API; parses `messages[0].id`.
  - `EmailChannel(host, port, user, password, sender)`, `name="email"`: sends via `smtplib` (wrapped in `asyncio.to_thread`).
  - `WebhookChannel(url)`, `name="webhook"`: POSTs `{recipient, body, template, data}` JSON to a configured URL.

- [ ] **Step 1: Write failing tests**

```python
# tests/framework/messaging/test_messaging.py
import asyncio
import pytest
from framework.messaging.base import OutboundMessage, MessageChannel
from framework.messaging.mock import MockChannel
from framework.messaging.registry import MessagingRegistry
from framework.errors import MessagingError


def test_mock_channel_records_and_acks():
    ch = MockChannel()
    res = asyncio.run(ch.send(OutboundMessage(recipient="+1", body="hi")))
    assert res.ok and ch.sent[0].body == "hi"


def test_mock_satisfies_protocol():
    assert isinstance(MockChannel(), MessageChannel)


def test_registry_routes_to_named_channel():
    reg = MessagingRegistry(); reg.add(MockChannel())
    res = asyncio.run(reg.send(channel="mock", recipient="+1", body="yo"))
    assert res.ok


def test_registry_unknown_channel_raises():
    with pytest.raises(MessagingError):
        asyncio.run(MessagingRegistry().send(channel="nope", recipient="+1", body="x"))
```

```python
# tests/framework/messaging/test_whatsapp.py
import asyncio
import httpx
import respx
from framework.messaging.whatsapp import WhatsAppChannel
from framework.messaging.base import OutboundMessage


@respx.mock
def test_whatsapp_sends_and_parses_id():
    respx.post("https://graph.facebook.com/v20.0/PNID/messages").mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "wamid.123"}]})
    )
    ch = WhatsAppChannel(access_token="tok", phone_number_id="PNID")
    res = asyncio.run(ch.send(OutboundMessage(recipient="+919900", body="hi")))
    assert res.ok and res.provider_message_id == "wamid.123"
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/messaging/ -v`
Expected: FAIL — `No module named 'framework.messaging'`

- [ ] **Step 3: Implement base + mock + registry**

```python
# framework/messaging/__init__.py
```

```python
# framework/messaging/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class OutboundMessage:
    recipient: str
    body: str
    template: str | None = None
    data: dict = field(default_factory=dict)


@dataclass
class DeliveryResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None


@runtime_checkable
class MessageChannel(Protocol):
    name: str

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        ...
```

```python
# framework/messaging/mock.py
from __future__ import annotations

from framework.messaging.base import DeliveryResult, OutboundMessage


class MockChannel:
    name = "mock"

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        self.sent.append(msg)
        return DeliveryResult(ok=True, provider_message_id=f"mock-{len(self.sent)}")
```

```python
# framework/messaging/registry.py
from __future__ import annotations

from framework.errors import MessagingError
from framework.messaging.base import DeliveryResult, MessageChannel, OutboundMessage


class MessagingRegistry:
    def __init__(self) -> None:
        self._channels: dict[str, MessageChannel] = {}

    def add(self, channel: MessageChannel) -> None:
        self._channels[channel.name] = channel

    async def send(self, *, channel: str, recipient: str, body: str,
                   template: str | None = None, data: dict | None = None) -> DeliveryResult:
        if channel not in self._channels:
            raise MessagingError(f"Unknown channel '{channel}'")
        msg = OutboundMessage(recipient=recipient, body=body, template=template, data=data or {})
        return await self._channels[channel].send(msg)
```

- [ ] **Step 4: Implement WhatsApp, Email, Webhook**

```python
# framework/messaging/whatsapp.py
from __future__ import annotations

import httpx

from framework.messaging.base import DeliveryResult, OutboundMessage


class WhatsAppChannel:
    name = "whatsapp"

    def __init__(self, access_token: str, phone_number_id: str,
                 base_url: str = "https://graph.facebook.com/v20.0", timeout: float = 30.0):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": msg.recipient,
            "type": "text",
            "text": {"body": msg.body},
        }
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
            mid = (resp.json().get("messages") or [{}])[0].get("id")
            return DeliveryResult(ok=True, provider_message_id=mid)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc))
```

```python
# framework/messaging/email.py
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from framework.messaging.base import DeliveryResult, OutboundMessage


class EmailChannel:
    name = "email"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str):
        self.host, self.port = host, port
        self.user, self.password, self.sender = user, password, sender

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        def _send() -> DeliveryResult:
            em = EmailMessage()
            em["From"], em["To"] = self.sender, msg.recipient
            em["Subject"] = msg.template or "Notification"
            em.set_content(msg.body)
            with smtplib.SMTP(self.host, self.port) as s:
                s.starttls()
                if self.user:
                    s.login(self.user, self.password)
                s.send_message(em)
            return DeliveryResult(ok=True)
        try:
            return await asyncio.to_thread(_send)
        except Exception as exc:  # noqa: BLE001
            return DeliveryResult(ok=False, error=str(exc))
```

```python
# framework/messaging/webhook.py
from __future__ import annotations

import httpx

from framework.messaging.base import DeliveryResult, OutboundMessage


class WebhookChannel:
    name = "webhook"

    def __init__(self, url: str, timeout: float = 15.0):
        self.url, self.timeout = url, timeout

    async def send(self, msg: OutboundMessage) -> DeliveryResult:
        payload = {"recipient": msg.recipient, "body": msg.body,
                   "template": msg.template, "data": msg.data}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.url, json=payload)
                resp.raise_for_status()
            return DeliveryResult(ok=True)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc))
```

Create empty `tests/framework/messaging/__init__.py`.

- [ ] **Step 5: Run, verify pass**

Run: `python -m pytest tests/framework/messaging/ -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add framework/messaging/ tests/framework/messaging/
git commit -m "feat(framework): messaging base, mock, registry, whatsapp/email/webhook channels"
```

---

### Task 13: Persistence — UserRepository, InMemory, SQLite

**Files:**
- Create: `framework/persistence/__init__.py`, `framework/persistence/base.py`, `framework/persistence/memory.py`, `framework/persistence/sqlite.py`
- Test: `tests/framework/persistence/test_repositories.py`

**Interfaces:**
- Produces:
  - `UserRepository(Protocol)`: `async get_by_phone(phone) -> UserContext | None`; `async get(user_id) -> UserContext | None`; `async upsert(user) -> None`.
  - `InMemoryUserRepository()`: dict-backed.
  - `SQLiteUserRepository(db_path)`: creates `users` table; columns `user_id PK, phone, location_name, lat, lon, urban_heat_offset, onboarding_json, role, locale, created_at`. Maps row<->UserContext: engine fields (`lat`, `lon`, `location_name`, `urban_heat_offset`, `onboarding`) live in `UserContext.metadata`. Uses `sqlite3` via `asyncio.to_thread`. `db_path` accepts a raw path; a `sqlite:///./x.db` URL is stripped to the file path.

- [ ] **Step 1: Write failing tests**

```python
# tests/framework/persistence/test_repositories.py
import asyncio
import pytest
from framework.context.user import UserContext
from framework.persistence.memory import InMemoryUserRepository
from framework.persistence.sqlite import SQLiteUserRepository


def _user():
    return UserContext(user_id="u1", phone="+919900", locale="ta",
                       metadata={"lat": 13.08, "lon": 80.27, "location_name": "Chennai"})


@pytest.mark.parametrize("make_repo", [
    lambda tmp: InMemoryUserRepository(),
    lambda tmp: SQLiteUserRepository(str(tmp / "t.db")),
])
def test_upsert_then_get_by_phone(make_repo, tmp_path):
    repo = make_repo(tmp_path)
    async def go():
        await repo.upsert(_user())
        u = await repo.get_by_phone("+919900")
        assert u is not None and u.user_id == "u1" and u.locale == "ta"
        assert u.metadata["lat"] == 13.08
    asyncio.run(go())


@pytest.mark.parametrize("make_repo", [
    lambda tmp: InMemoryUserRepository(),
    lambda tmp: SQLiteUserRepository(str(tmp / "t.db")),
])
def test_get_missing_returns_none(make_repo, tmp_path):
    repo = make_repo(tmp_path)
    assert asyncio.run(repo.get_by_phone("+000")) is None


def test_sqlite_upsert_is_idempotent(tmp_path):
    repo = SQLiteUserRepository(str(tmp_path / "t.db"))
    async def go():
        await repo.upsert(_user())
        await repo.upsert(_user())  # second upsert must not raise
        u = await repo.get("u1")
        assert u.user_id == "u1"
    asyncio.run(go())


def test_sqlite_strips_url_prefix(tmp_path):
    repo = SQLiteUserRepository(f"sqlite:///{tmp_path}/url.db")
    asyncio.run(repo.upsert(_user()))
    assert asyncio.run(repo.get("u1")).user_id == "u1"
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/persistence/ -v`
Expected: FAIL — `No module named 'framework.persistence'`

- [ ] **Step 3: Implement base + memory**

```python
# framework/persistence/__init__.py
```

```python
# framework/persistence/base.py
from __future__ import annotations

from typing import Protocol

from framework.context.user import UserContext


class UserRepository(Protocol):
    async def get_by_phone(self, phone: str) -> UserContext | None: ...
    async def get(self, user_id: str) -> UserContext | None: ...
    async def upsert(self, user: UserContext) -> None: ...
```

```python
# framework/persistence/memory.py
from __future__ import annotations

from framework.context.user import UserContext


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, UserContext] = {}

    async def get_by_phone(self, phone: str) -> UserContext | None:
        return next((u for u in self._by_id.values() if u.phone == phone), None)

    async def get(self, user_id: str) -> UserContext | None:
        return self._by_id.get(user_id)

    async def upsert(self, user: UserContext) -> None:
        self._by_id[user.user_id] = user
```

- [ ] **Step 4: Implement SQLite**

```python
# framework/persistence/sqlite.py
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

from framework.context.user import UserContext

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    phone TEXT,
    location_name TEXT,
    lat REAL,
    lon REAL,
    urban_heat_offset REAL,
    onboarding_json TEXT,
    role TEXT,
    locale TEXT,
    created_at TEXT
)
"""


class SQLiteUserRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path.replace("sqlite:///", "").replace("sqlite://", "")
        with self._conn() as c:
            c.execute(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _to_user(row: sqlite3.Row) -> UserContext:
        return UserContext(
            user_id=row["user_id"],
            phone=row["phone"],
            role=row["role"] or "user",
            locale=row["locale"] or "en",
            metadata={
                "lat": row["lat"],
                "lon": row["lon"],
                "location_name": row["location_name"],
                "urban_heat_offset": row["urban_heat_offset"],
                "onboarding": json.loads(row["onboarding_json"]) if row["onboarding_json"] else None,
            },
        )

    async def get_by_phone(self, phone: str) -> UserContext | None:
        return await asyncio.to_thread(self._query, "phone", phone)

    async def get(self, user_id: str) -> UserContext | None:
        return await asyncio.to_thread(self._query, "user_id", user_id)

    def _query(self, column: str, value: str) -> UserContext | None:
        with self._conn() as c:
            row = c.execute(f"SELECT * FROM users WHERE {column}=?", (value,)).fetchone()
        return self._to_user(row) if row else None

    async def upsert(self, user: UserContext) -> None:
        await asyncio.to_thread(self._upsert, user)

    def _upsert(self, user: UserContext) -> None:
        m = user.metadata
        with self._conn() as c:
            c.execute(
                """INSERT INTO users
                   (user_id, phone, location_name, lat, lon, urban_heat_offset,
                    onboarding_json, role, locale, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     phone=excluded.phone, location_name=excluded.location_name,
                     lat=excluded.lat, lon=excluded.lon,
                     urban_heat_offset=excluded.urban_heat_offset,
                     onboarding_json=excluded.onboarding_json,
                     role=excluded.role, locale=excluded.locale""",
                (user.user_id, user.phone, m.get("location_name"), m.get("lat"), m.get("lon"),
                 m.get("urban_heat_offset"),
                 json.dumps(m.get("onboarding")) if m.get("onboarding") is not None else None,
                 user.role, user.locale, datetime.now(timezone.utc).isoformat()),
            )
```

Create empty `tests/framework/persistence/__init__.py`.

- [ ] **Step 5: Run, verify pass**

Run: `python -m pytest tests/framework/persistence/ -v`
Expected: PASS (8 tests including parametrized)

- [ ] **Step 6: Commit**

```bash
git add framework/persistence/ tests/framework/persistence/
git commit -m "feat(framework): UserRepository protocol, in-memory + SQLite implementations"
```

---

### Task 14: Boundary enforcement (import-linter)

**Files:**
- Create: `.importlinter`
- Test: `tests/framework/test_boundary.py`

**Interfaces:**
- Produces: a CI-runnable contract that `framework` must not import `prana` or `backend`.

- [ ] **Step 1: Write failing test**

```python
# tests/framework/test_boundary.py
import subprocess
import sys


def test_framework_does_not_import_prana_or_backend():
    result = subprocess.run(
        [sys.executable, "-m", "importlinter", "--config", ".importlinter"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/framework/test_boundary.py -v`
Expected: FAIL — import-linter exits non-zero (no `.importlinter` config) OR config-missing error.

- [ ] **Step 3: Implement `.importlinter`**

```ini
[importlinter]
root_packages =
    framework
    prana
    backend

[importlinter:contract:framework-is-independent]
name = framework must not depend on prana or backend
type = forbidden
source_modules =
    framework
forbidden_modules =
    prana
    backend
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/framework/test_boundary.py -v`
Expected: PASS (framework imports nothing from prana/backend)

- [ ] **Step 5: Commit**

```bash
git add .importlinter tests/framework/test_boundary.py
git commit -m "test(framework): enforce framework independence via import-linter"
```

---

### Task 15: PRANA consumer — get_risk tool, bootstrap, WhatsApp webhook

**Files:**
- Create: `prana/ai_tools/__init__.py`, `prana/ai_tools/risk.py`, `prana/bot/__init__.py`, `prana/bot/bootstrap.py`, `prana/bot/whatsapp_webhook.py`
- Test: `tests/prana/test_risk_tool.py`, `tests/prana/test_whatsapp_webhook.py`

**Interfaces:**
- Consumes: `framework` (Agent, Tool, ToolRegistry, UserContext, MockProvider/providers, MessagingRegistry, SQLiteUserRepository), `prana.prana_system.PRANASystem`.
- Produces:
  - `get_risk(*, ctx: UserContext) -> dict` — builds `PRANASystem` from `ctx.metadata`, calls `update_all(lat, lon)`, returns trimmed dict with REAL keys: `ccri`, `risk_level`, `ndt`, `rds_mid` (from `result["rds"]["rds_mid"]`), `consecutive_nights` (from `result["rds"]["consecutive_nights"]`), `alert_message`, `as_of` (from `result["timestamp"]`).
  - `risk_tool: Tool` named `get_risk`, no LLM params, `required_permission=None`.
  - `prana/bot/bootstrap.py`: `build_registry()`, `build_messaging()`, `build_repo()`, `build_agent_provider()` returning configured framework objects.
  - `prana/bot/whatsapp_webhook.py`: a FastAPI `APIRouter` with `GET /webhook/whatsapp` (verify challenge) and `POST /webhook/whatsapp` (signature verify -> lookup user -> agent -> reply). Dependencies injected via module-level singletons created from bootstrap so tests can monkeypatch them.

- [ ] **Step 1: Write failing test for get_risk tool (PRANASystem mocked)**

```python
# tests/prana/test_risk_tool.py
import asyncio
from unittest.mock import patch
from datetime import datetime
from framework.context.user import UserContext
from framework.tools.base import ToolRegistry
from prana.ai_tools.risk import get_risk, risk_tool


def _fake_result():
    return {
        "ccri": 72.3, "risk_level": "HIGH", "ndt": 34.1,
        "rds": {"rds_mid": 150.0, "consecutive_nights": 3, "rds_low": 140, "rds_high": 160},
        "timestamp": datetime(2026, 6, 26, 21, 0), "alert_message": "Stay cool tonight.",
    }


def test_get_risk_returns_trimmed_real_keys():
    ctx = UserContext(user_id="u1", metadata={"lat": 13.08, "lon": 80.27,
                                              "location_name": "Chennai"})
    with patch("prana.ai_tools.risk.PRANASystem") as MockSys:
        MockSys.return_value.update_all.return_value = _fake_result()
        out = get_risk(ctx=ctx)
    assert out["ccri"] == 72.3 and out["risk_level"] == "HIGH"
    assert out["rds_mid"] == 150.0 and out["consecutive_nights"] == 3
    assert out["as_of"] == "2026-06-26T21:00:00"


def test_get_risk_tool_via_registry():
    reg = ToolRegistry(); reg.register(risk_tool)
    ctx = UserContext(user_id="u1", metadata={"lat": 13.08, "lon": 80.27})
    with patch("prana.ai_tools.risk.PRANASystem") as MockSys:
        MockSys.return_value.update_all.return_value = _fake_result()
        res = asyncio.run(reg.execute("get_risk", {}, ctx))
    assert res.ok and res.data["risk_level"] == "HIGH"
```

- [ ] **Step 2: Run, verify fails**

Run: `python -m pytest tests/prana/test_risk_tool.py -v`
Expected: FAIL — `No module named 'prana.ai_tools'`

- [ ] **Step 3: Implement get_risk tool**

```python
# prana/ai_tools/__init__.py
```

```python
# prana/ai_tools/risk.py
"""PRANA's get_risk tool — wraps the deterministic scoring engine for the agent."""
from __future__ import annotations

from framework.context.user import UserContext
from framework.tools.base import Tool
from prana.config import OPENAQ_API_KEY, OPENWEATHER_API_KEY
from prana.prana_system import PRANASystem


def get_risk(*, ctx: UserContext) -> dict:
    meta = ctx.metadata
    system = PRANASystem(
        api_key=OPENWEATHER_API_KEY,
        location_name=meta.get("location_name", "Current location"),
        urban_heat_offset=meta.get("urban_heat_offset"),
        openaq_api_key=OPENAQ_API_KEY,
        onboarding_data=meta.get("onboarding"),
    )
    result = system.update_all(meta["lat"], meta["lon"])
    if not result:
        return {"error": "Risk data is temporarily unavailable."}
    rds = result["rds"]
    ts = result["timestamp"]
    return {
        "ccri": result["ccri"],
        "risk_level": result["risk_level"],
        "ndt": result["ndt"],
        "rds_mid": rds["rds_mid"],
        "consecutive_nights": rds["consecutive_nights"],
        "alert_message": result["alert_message"],
        "as_of": ts.isoformat() if hasattr(ts, "isoformat") else ts,
    }


risk_tool = Tool(
    name="get_risk",
    description=(
        "Get the user's current compound climate risk (heat + pollution + sleep "
        "recovery). Call this whenever the user asks about their risk, heat, air "
        "quality, sleep, or why an alert was sent."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    fn=get_risk,
    required_permission=None,
)
```

- [ ] **Step 4: Run get_risk tests, verify pass**

Run: `python -m pytest tests/prana/test_risk_tool.py -v`
Expected: PASS (2 tests). Create empty `tests/prana/__init__.py` if needed.

- [ ] **Step 5: Implement bootstrap**

```python
# prana/bot/__init__.py
```

```python
# prana/bot/bootstrap.py
"""Wires framework components for PRANA's bot at startup."""
from __future__ import annotations

from framework.ai.factory import build_provider
from framework.config.settings import FrameworkSettings
from framework.messaging.registry import MessagingRegistry
from framework.messaging.whatsapp import WhatsAppChannel
from framework.persistence.sqlite import SQLiteUserRepository
from framework.tools.base import ToolRegistry
from prana.ai_tools.risk import risk_tool
from prana.config import DATABASE_URL

settings = FrameworkSettings()


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(risk_tool)
    return reg


def build_provider_chain():
    return build_provider(settings)


def build_messaging() -> MessagingRegistry:
    reg = MessagingRegistry()
    reg.add(WhatsAppChannel(settings.whatsapp_access_token, settings.whatsapp_phone_number_id))
    return reg


def build_repo() -> SQLiteUserRepository:
    return SQLiteUserRepository(DATABASE_URL)
```

- [ ] **Step 6: Write failing webhook test (everything mocked)**

```python
# tests/prana/test_whatsapp_webhook.py
import hashlib
import hmac
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from framework.ai.base import ChatResponse, ToolCall, Usage
from framework.ai.mock import MockProvider
from framework.context.user import UserContext
from framework.messaging.mock import MockChannel
from framework.messaging.registry import MessagingRegistry
from framework.persistence.memory import InMemoryUserRepository
from framework.tools.base import ToolRegistry
from prana.ai_tools.risk import risk_tool
from prana import bot
import prana.bot.whatsapp_webhook as wh


@pytest.fixture
def client(monkeypatch):
    repo = InMemoryUserRepository()
    msg = MessagingRegistry(); mock_channel = MockChannel(); msg.add(mock_channel)
    reg = ToolRegistry(); reg.register(risk_tool)
    provider = MockProvider(responses=[
        ChatResponse(content=None, tool_calls=[ToolCall("1", "get_risk", {})], usage=Usage()),
        ChatResponse(content="Your risk is HIGH tonight.", usage=Usage()),
    ])
    monkeypatch.setattr(wh, "user_repo", repo)
    monkeypatch.setattr(wh, "messaging", msg)
    monkeypatch.setattr(wh, "registry", reg)
    monkeypatch.setattr(wh, "provider", provider)
    monkeypatch.setattr(wh, "APP_SECRET", "secret")
    monkeypatch.setattr(wh, "VERIFY_TOKEN", "verifytok")
    # patch the engine so get_risk doesn't hit network
    from unittest.mock import patch
    from datetime import datetime
    patcher = patch("prana.ai_tools.risk.PRANASystem")
    MockSys = patcher.start()
    MockSys.return_value.update_all.return_value = {
        "ccri": 72, "risk_level": "HIGH", "ndt": 34, "alert_message": "hot",
        "rds": {"rds_mid": 150, "consecutive_nights": 3}, "timestamp": datetime(2026, 6, 26),
    }
    app = FastAPI(); app.include_router(wh.router)
    yield TestClient(app), repo, mock_channel
    patcher.stop()


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_challenge(client):
    c, _, _ = client
    r = c.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "verifytok", "hub.challenge": "12345"})
    assert r.status_code == 200 and r.text == "12345"


def test_known_user_gets_agent_reply(client):
    c, repo, channel = client
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        repo.upsert(UserContext(user_id="u1", phone="+919900",
                                metadata={"lat": 13.08, "lon": 80.27})))
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "+919900", "text": {"body": "why is my risk high?"}}]}}]}]}).encode()
    r = c.post("/webhook/whatsapp", content=body,
               headers={"X-Hub-Signature-256": _sign(body, "secret")})
    assert r.status_code == 200
    assert channel.sent[-1].body == "Your risk is HIGH tonight."
    assert channel.sent[-1].recipient == "+919900"


def test_forged_signature_rejected(client):
    c, _, _ = client
    body = b'{"entry":[]}'
    r = c.post("/webhook/whatsapp", content=body,
               headers={"X-Hub-Signature-256": "sha256=wrong"})
    assert r.status_code == 403
```

- [ ] **Step 7: Run, verify fails**

Run: `python -m pytest tests/prana/test_whatsapp_webhook.py -v`
Expected: FAIL — `No module named 'prana.bot.whatsapp_webhook'`

- [ ] **Step 8: Implement webhook**

```python
# prana/bot/whatsapp_webhook.py
"""WhatsApp Cloud API webhook: message -> agent -> reply."""
from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Request, Response

from framework import agent as make_agent
from prana.bot.bootstrap import (
    build_messaging, build_provider_chain, build_registry, build_repo, settings,
)

router = APIRouter()

# Module-level singletons (tests monkeypatch these)
registry = build_registry()
messaging = build_messaging()
user_repo = build_repo()
provider = build_provider_chain()
APP_SECRET = settings.whatsapp_app_secret
VERIFY_TOKEN = settings.whatsapp_verify_token

_ONBOARD = "Welcome to PRANA. Reply START to set up heat alerts for your area."


@router.get("/webhook/whatsapp")
async def verify(request: Request) -> Response:
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


def _valid_signature(body: bytes, header: str | None) -> bool:
    if not header or not APP_SECRET:
        return False
    expected = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def _parse(payload: dict) -> tuple[str, str] | None:
    try:
        msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        return msg["from"], msg["text"]["body"]
    except (KeyError, IndexError, TypeError):
        return None


@router.post("/webhook/whatsapp")
async def receive(request: Request) -> Response:
    body = await request.body()
    if not _valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=403)

    import json
    parsed = _parse(json.loads(body))
    if not parsed:
        return Response(status_code=200)  # status callbacks etc. — ack and ignore
    phone, text = parsed

    user = await user_repo.get_by_phone(phone)
    if user is None:
        await messaging.send(channel="whatsapp", recipient=phone, body=_ONBOARD)
        return Response(status_code=200)

    ag = make_agent(provider, registry, max_steps=settings.agent_max_steps,
                    temperature=settings.agent_temperature)
    result = await ag.run(text, user)
    await messaging.send(channel="whatsapp", recipient=phone,
                         body=result.answer or "Sorry, please try again.")
    return Response(status_code=200)
```

- [ ] **Step 9: Run all PRANA consumer tests, verify pass**

Run: `python -m pytest tests/prana/ -v`
Expected: PASS (5 tests)

- [ ] **Step 10: Commit**

```bash
git add prana/ai_tools/ prana/bot/ tests/prana/
git commit -m "feat(prana): get_risk tool, bot bootstrap, WhatsApp webhook (agent-backed)"
```

---

### Task 16: Mount webhook, migrate sleep-checkin off backend/llm.py, full suite, docs

**Files:**
- Modify: `backend/main.py` (mount the webhook router)
- Modify: `backend/llm.py` (point `extract_sleep_checkin`'s LLM call at framework provider) OR leave + note. See steps.
- Create: `docs/framework/README.md`
- Test: full suite run

**Interfaces:**
- Consumes: everything above.
- Produces: a running app exposing `/webhook/whatsapp`; framework README.

- [ ] **Step 1: Mount router in `backend/main.py`**

After `app = FastAPI(...)` block and middleware, add:

```python
from prana.bot.whatsapp_webhook import router as whatsapp_router  # noqa: E402
app.include_router(whatsapp_router)
```

- [ ] **Step 2: Verify app imports cleanly**

Run: `python -c "from backend.main import app; print([r.path for r in app.routes])"`
Expected: output includes `/webhook/whatsapp`

- [ ] **Step 3: Migrate sleep-checkin LLM call (DRY — one LLM path)**

In `backend/llm.py`, replace the body of the non-deterministic branch of `extract_sleep_checkin` (the part that builds `prompt` and calls `self.chat`) to use the framework provider instead of the legacy client. Minimal change: add at top of `backend/llm.py`:

```python
from framework.ai.factory import build_provider
from framework.config.settings import FrameworkSettings
from framework.ai.base import Message, Role
```

Replace the fallback block (after the four numbered-reply branches) with:

```python
        provider = build_provider(FrameworkSettings())
        resp = provider.chat([
            Message(Role.SYSTEM, (
                "Extract PRANA sleep recovery check-in data. Return only compact JSON "
                "with sleep_environment, sleep_quality, cooling_issue, power_issue, confidence.")),
            Message(Role.USER, user_message),
        ], temperature=0)
        return {"raw_llm_response": resp.content, "confidence": "low"}
```

Leave the legacy `LLMClient.chat`/`_chat_openrouter`/`_chat_ollama` in place for now (other callers may exist); they are dead-path once nothing calls them. Add a module docstring note: "Superseded by framework.ai; retained until all callers migrated."

- [ ] **Step 4: Run the FULL test suite**

Run: `python -m pytest -v`
Expected: all framework + prana + existing PRANA formula tests PASS. (If an existing test breaks due to the `backend/llm.py` edit, revert Step 3's edit and instead leave `backend/llm.py` untouched, noting migration as future work — do not break existing tests.)

- [ ] **Step 5: Write framework README**

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/llm.py docs/framework/README.md
git commit -m "feat(prana): mount whatsapp webhook, migrate sleep-checkin to framework, add docs"
```

---

## Self-Review

**1. Spec coverage:**
- §1 driving use case -> Task 15 (webhook -> agent -> get_risk -> reply). ✓
- §2 package structure -> Tasks 1-13 file layout matches. ✓
- §2 boundary rule (no prana import) -> Task 14. ✓
- §2 LLM never touches engine/DB -> get_risk is the only path (Task 15); enforced by design. ✓
- §3 LLMProvider/Tool/UserContext/MessageChannel/UserRepository interfaces -> Tasks 2,5,6,4,12,13. ✓
- §3 sync+async tools, cost in Usage -> Task 6, Task 2 (Usage.__add__), Task 8 (sums into AgentResult). ✓
- §4 agent loop, native+ReAct, errors-feed-back, max_steps, system prompt, fallback chain -> Tasks 7,8,10. ✓
- §4 prompt-injection light guard -> Task 8 wraps tool results in `<tool_result>` delimiters + system prompt. ✓
- §5 get_risk (real keys), webhook (sig verify, onboarding fallback), bootstrap, SQLite user table -> Tasks 13,15. ✓
- §6 config env-driven, provider swap by list -> Task 11. ✓
- §7 testing (mock everywhere, respx adapters, boundary, slice) -> every task + Tasks 9,14,15. ✓
- §8 out-of-scope items -> none implemented (correct). ✓
- §9 effort -> tracked separately.

**2. Placeholder scan:** No TBD/TODO/"add error handling" — every code step has full code. ✓

**3. Type consistency:**
- `ChatResponse(content, tool_calls, usage, raw)` consistent across Tasks 2,3,8,9,10. ✓
- `ToolResult(ok, data, error)` consistent Tasks 5,6,8. ✓
- `get_risk` real keys (`risk_level` not `ccri_band`; `rds_mid` from nested `rds`) consistent Task 15 with verified `prana_system.py`. ✓
- `Agent.run(user_message, ctx, history=None)` signature consistent Task 8 & 15. ✓
- Facade `framework.agent(provider, registry, **kw)` consistent Task 11 & 15. ✓

**Note carried into execution:** Task 16 Step 3 (sleep-checkin migration) has an explicit fallback instruction to revert if it breaks existing tests — this protects the "don't break working code" constraint.
