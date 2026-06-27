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
