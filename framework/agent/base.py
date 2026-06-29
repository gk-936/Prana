from __future__ import annotations

import json
from typing import Callable

from framework.agent.result import AgentResult, TraceEntry
from framework.ai.base import LLMProvider, Message, Role, Usage
from framework.context.user import UserContext
from framework.tools.base import ToolRegistry

_DEFAULT_SYSTEM = (
    "You are a helpful assistant for {name} (locale={locale}). "
    "For greetings, small talk, or general questions, reply directly and "
    "conversationally WITHOUT calling a tool. "
    "Only when the user asks about their own data (e.g. their risk, heat, air "
    "quality, or sleep) must you call a tool to get it — you have no such data "
    "of your own, so never invent numbers or facts about the user."
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
            # Always offer tools; each provider adapts to its own tool-calling
            # style (native API or ReAct text) and returns a normalized
            # ChatResponse with tool_calls populated when a call is requested.
            resp = self.provider.chat(
                messages, tools=self.registry.schemas(), temperature=self.temperature
            )
            tool_calls = resp.tool_calls
            answer = resp.content

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
