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
