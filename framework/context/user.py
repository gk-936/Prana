# framework/context/user.py
from __future__ import annotations

from typing import FrozenSet, Optional

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    user_id: str
    organization_id: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str = "user"
    permissions: FrozenSet[str] = Field(default_factory=frozenset)
    locale: str = "en"
    timezone: str = "UTC"
    preferences: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    def has_permission(self, perm: str) -> bool:
        return self.role == "admin" or perm in self.permissions
