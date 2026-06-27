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
