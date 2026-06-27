from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable

from framework.context.user import UserContext
from framework.errors import PermissionDeniedError, ToolError


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
        from framework.tools.permissions import check_permission

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
