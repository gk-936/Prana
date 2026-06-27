from __future__ import annotations

import json
from typing import Callable

from framework.agent.react import build_react_messages, parse_react_response
from framework.agent.result import AgentResult, TraceEntry
from framework.ai.base import LLMProvider, Message, Role, Usage
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
        total: Usage | None = None
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

            total = resp.usage if total is None else total + resp.usage

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
            answer=_FALLBACK_ANSWER,
            usage=total or Usage(),
            trace=trace,
            steps=self.max_steps,
        )
