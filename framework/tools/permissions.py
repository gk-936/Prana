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
