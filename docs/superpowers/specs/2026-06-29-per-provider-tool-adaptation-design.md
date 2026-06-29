# Per-Provider Tool-Call Adaptation — Design Spec

**Date:** 2026-06-29
**Status:** Approved
**Author:** Gokul + Claude (brainstorming session)

## 1. Problem

`framework/ai/fallback.py`'s `FallbackProvider.supports_native_tools` returns
only `self.providers[0].supports_native_tools`. With the production chain
`[openrouter, ollama]`, that reports `True` (openrouter supports native tool
calls). `framework/agent/base.py`'s `Agent.run()` branches on the provider's
`supports_native_tools`:

```python
if self.provider.supports_native_tools:
    resp = self.provider.chat(messages, tools=self.registry.schemas(), ...)
    tool_calls, answer = resp.tool_calls, resp.content
else:
    react_msgs = build_react_messages(messages, self.registry.schemas())
    resp = self.provider.chat(react_msgs, tools=None, ...)
    tool_calls, answer = parse_react_response(resp.content or "")
```

Because the chain reports `True`, the Agent takes the native-tools path and
never builds the ReAct prompt. Inside `FallbackProvider.chat`, openrouter
fails (no API key) and the chain falls through to Ollama — but Ollama is
called with `use_tools = None` (since Ollama's own
`supports_native_tools=False`) **and no ReAct instruction**, because the
Agent already decided not to build one. So `phi4-mini` receives only the bare
system prompt + user message, with no tool definitions and no "reply with
JSON" instruction, and answers conversationally.

Observed symptom: a WhatsApp message "What is my risk now" returns a generic
"I'm sorry, I don't possess personal information…" reply instead of calling
`get_risk`. Confirmed via a full `Agent.run` trace showing `steps=1`, empty
tool trace — the agent never called any tool.

This was a **known, explicitly-deferred limitation**: the original framework
plan (`docs/superpowers/plans/2026-06-26-prana-ai-framework.md`, line ~1446)
states *"keep all providers in a chain homogeneous in tool support where
possible. Test covers the failover behavior, not mixed capability."* The
production `[openrouter, ollama]` chain is exactly the mixed-capability case
that was never supported.

## 2. Core Idea

Move tool-style handling **out of the Agent and into each provider**. The
Agent stops branching on `supports_native_tools`; it always calls
`provider.chat(messages, tools=schemas)` and reads a normalized
`ChatResponse` (`.tool_calls` populated when the model wants to call a tool,
`.content` holding the final text answer otherwise). Each provider does
whatever its own API requires internally to satisfy that contract.

`ReAct` (prompt-based tool-calling over a plain text model) becomes an
internal implementation detail of `OllamaProvider`, not an Agent concern.

## 3. The Contract Change

`LLMProvider.chat(messages, *, tools=None, temperature=...)` gains a firm
contract:

> Given `tools`, the provider returns any tool calls the model decided to
> make in `ChatResponse.tool_calls`, and the final natural-language answer
> (when no tool call is made) in `ChatResponse.content`. How the provider
> achieves this — native function-calling API, or prompt-engineered ReAct
> text that it parses itself — is internal to the provider.

`supports_native_tools` is demoted to **informational only**. It remains on
the protocol and on each provider (for introspection/debugging), but
`Agent.run()` no longer uses it for control flow.

## 4. Components Changed

### 4.1 `framework/ai/ollama.py` — `OllamaProvider.chat()`

When `tools` is passed, internally:

1. `messages = build_react_messages(messages, tools)` — append the ReAct
   instruction system message. **Re-applied on every `chat()` call**, so
   multi-step follow-up calls that carry prior `Role.TOOL` results get
   re-framed each time (matches what the Agent's old ReAct branch did per
   loop iteration, just relocated). `build_react_messages` already does
   `list(messages) + [instruction]`, so any `Role.TOOL` / `Role.ASSISTANT`
   messages in the conversation pass through into the text prompt.
2. POST to `{base_url}/api/chat` as today.
3. Parse the response:
   - If Ollama returned a native `message.tool_calls` field (some models,
     e.g. `gpt-oss`, use it instead of following the ReAct text instruction),
     map the first call into `ChatResponse.tool_calls`. *(Already implemented
     in commit `b8a3338` — that fix synthesized ReAct JSON into content; this
     spec supersedes it by parsing into `tool_calls` directly, see §4.5.)*
   - Otherwise run `parse_react_response(content)` to extract either a
     `ToolCall` or a final answer.
4. Return `ChatResponse(content=<answer or None>, tool_calls=<list>, raw=data)`.

When `tools` is `None` (no tools available), behave as a plain chat: return
`ChatResponse(content=message.content)`.

`OllamaProvider` imports `build_react_messages` and `parse_react_response`
from `framework.agent.react`. This is within the `framework` package, so it
does not violate the `.importlinter` `framework-is-independent` contract
(which only forbids `framework` importing `prana`/`backend`). ReAct stays in
`framework/agent/react.py` (not moved), per the chosen approach.

Verified empirically: `phi4-mini` correctly reads a `Role.TOOL`
`<tool_result>{…}</tool_result>` message on the second iteration and returns
a clean `{"answer": "…"}` grounded in the tool data.

### 4.2 `parse_react_response` reuse

`parse_react_response(content) -> (list[ToolCall], str | None)` already
exists and is tested. `OllamaProvider` uses it directly; no change needed to
`framework/agent/react.py`.

### 4.3 `framework/ai/fallback.py` — `FallbackProvider`

- `chat()` passes `tools` to **every** provider's `chat()` (drop the
  `use_tools = tools if provider.supports_native_tools else None` gating —
  each provider now handles `tools` correctly on its own). Keep the
  try-next-on-exception loop unchanged.
- `supports_native_tools` property: keep it for introspection but it no
  longer drives Agent control flow. Change its semantics to `all(p.supports_
  native_tools for p in self.providers)` so it honestly reports "every
  provider in this chain uses native tools" rather than guessing from the
  first. (This is the more truthful answer for any external caller and makes
  the existing `test_supports_native_tools_from_first` test's intent
  explicit — see §6.)

### 4.4 `framework/agent/base.py` — `Agent.run()`

Remove the `if self.provider.supports_native_tools:` / `else:` branch
entirely. Replace with a single uniform call:

```python
resp = self.provider.chat(
    messages, tools=self.registry.schemas(), temperature=self.temperature
)
tool_calls, answer = resp.tool_calls, resp.content
```

The rest of the loop (append `Role.ASSISTANT` with tool_calls, execute each
tool, append `Role.TOOL` results, re-loop up to `max_steps`, fallback answer)
is unchanged. `build_react_messages` / `parse_react_response` imports are
removed from `base.py` (now only used inside `OllamaProvider`).

### 4.5 Relationship to commit `b8a3338`

Commit `b8a3338` ("fix(ai): synthesize ReAct JSON when Ollama uses native
tool_calls") was a narrower fix made mid-debugging: it converted Ollama's
native `tool_calls` field into a ReAct-JSON string in `content`, so the
Agent's old ReAct branch (`parse_react_response`) would pick it up. With this
spec, `OllamaProvider` now owns parsing end-to-end and populates
`ChatResponse.tool_calls` directly — so the synthesize-into-content step
becomes an internal detail. The net behavior for native-`tool_calls`
responses must remain: a tool call is surfaced. The implementation may keep
the synthesize-then-parse path or map directly to `tool_calls`; either is
acceptable as long as the tests in §6 pass.

## 5. Data Flow (after fix)

```
Agent.run
  -> provider.chat(messages, tools=schemas)          # always, uniform
       FallbackProvider.chat:
         try openrouter.chat(messages, tools=schemas) # native; fails (no key)
         try ollama.chat(messages, tools=schemas)     # ReAct, internal
              build_react_messages(messages, tools)
              POST /api/chat
              parse native tool_calls OR parse_react_response
              -> ChatResponse(content / tool_calls)
  <- ChatResponse
  if tool_calls: execute, append Role.TOOL results, loop
  else: return answer
```

## 6. Testing

New / changed tests (pytest, respx for HTTP mocks, mirroring
`tests/framework/ai/test_adapters.py` and `tests/framework/agent/test_agent.py`):

- **OllamaProvider, ReAct text tool call:** `chat(messages, tools=[get_risk
  schema])` where the mocked Ollama response `content` is
  ` ```json\n{"tool":"get_risk","args":{}}\n``` ` → returns
  `ChatResponse.tool_calls == [ToolCall(name="get_risk", arguments={})]`,
  `content is None`.
- **OllamaProvider, native tool_calls:** mocked response has
  `message.tool_calls=[{function:{name:get_risk,arguments:{}}}]`, empty
  content → `ChatResponse.tool_calls` populated (preserves `b8a3338`
  behavior through the new contract).
- **OllamaProvider, plain answer:** mocked response is
  `{"answer":"you are safe"}` → `content == "you are safe"`,
  `tool_calls == []`.
- **OllamaProvider, no tools passed:** `chat(messages, tools=None)` → plain
  `content` from `message.content`, no ReAct instruction added (regression
  guard for the existing `test_ollama_parses_content`).
- **Agent over mixed FallbackProvider (the bug's regression test):**
  `Agent.run` with `FallbackProvider([native-provider-that-raises,
  OllamaProvider-mock])`. The native one raises; the Ollama mock returns a
  ReAct tool call then (2nd call) a final answer. Assert the tool executed
  (trace non-empty) and the final answer is the grounded one — this is the
  end-to-end test that would have caught the original bug.
- **FallbackProvider passes tools to every provider:** assert the Ollama
  mock received `tools` (not `None`) even though it sits behind a native
  provider.
- **`test_fallback.py::test_supports_native_tools_from_first`:** update to
  reflect the new `all(...)` semantics (rename and adjust assertion). A
  single-provider chain with a non-native provider still reports `False`; a
  mixed chain now reports `False` (previously would report the first
  provider's value).
- **`test_agent.py` — tests that already use real `ChatResponse.tool_calls`
  still pass:** `test_native_tool_call_then_answer`,
  `test_max_steps_guard`, and `test_permission_error_feeds_back_not_crash`
  all script `MockProvider` responses with populated `tool_calls` and read
  them via the uniform path. These pass unchanged (the Agent already read
  `resp.tool_calls` on the native branch; that branch is now the only path).
- **`test_agent.py::test_react_fallback_path` MUST be rewritten.** It
  currently encodes the OLD contract: a `MockProvider(supports_native_tools=
  False)` returning `content='{"tool":"get_risk","args":{}}'` (raw ReAct
  JSON), expecting the **Agent** to call `parse_react_response`, and asserts
  `provider.calls[0]["tools"] is None`. Under the new design the Agent never
  parses ReAct and always passes `tools=schemas`, so a bare `MockProvider`
  emitting raw ReAct-JSON in `content` would be parsed by nobody. Replace
  this test's intent — "the ReAct path works" — with a test at the
  **`OllamaProvider`** level (an `@respx.mock` test in `test_adapters.py`
  that feeds Ollama a ReAct-JSON `content` and asserts `ChatResponse.
  tool_calls` is populated; already listed above). The Agent-level behavior
  it used to cover (tool call → execute → final answer) is now covered by
  the "Agent over mixed FallbackProvider" integration test above. Remove the
  `provider.calls[0]["tools"] is None` assertion entirely — it asserts the
  exact behavior this fix deletes.
- **`MockProvider`** keeps its `supports_native_tools` constructor arg (still
  valid for introspection tests), but tests should no longer rely on it to
  steer Agent control flow.

All existing passing tests must remain green; the 4 known pre-existing
unrelated failures (`test_factory.py` x2, `test_settings.py::test_llm_
providers_from_env`, `test_register.py::test_register_saves_user_with_
onboarding_metadata`) are out of scope.

## 7. Out of Scope

- **Twilio's 15-second webhook timeout.** This fix makes the agent *correct*
  (it calls the tool and grounds its answer). Whether a synchronous reply
  fits in 15s is a separate latency concern, addressed elsewhere (e.g. an
  ack-200-then-reply-async pattern via Twilio's REST API). Not part of this
  spec.
- **Model choice** (phi4-mini vs gpt-oss vs openrouter) and chain
  composition — unchanged.
- **Streaming responses** — providers remain non-streaming.
- **Native multi-tool-call in one turn for Ollama** — ReAct parses a single
  tool call per turn, as today; multi-call fan-out is not introduced here.

Related: [[2026-06-26-prana-ai-framework-design]]
