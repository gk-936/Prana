from __future__ import annotations

from typing import Protocol

from framework.context.user import UserContext


class UserRepository(Protocol):
    async def get_by_phone(self, phone: str) -> UserContext | None: ...
    async def get(self, user_id: str) -> UserContext | None: ...
    async def upsert(self, user: UserContext) -> None: ...
