"""`GET /me` (docs/04_API_SPEC.md §2) — current user, role, account, permissions list."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.ids import format_id
from app.core.security import ROLE_PERMISSIONS
from app.db.models.tenancy import User

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    user_id: str
    email: str
    name: str
    role: str
    account_id: str | None
    permissions: list[str]


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        user_id=format_id("user", user.user_id),
        email=user.email,
        name=user.name,
        role=user.role.value,
        account_id=format_id("account", user.account_id) if user.account_id else None,
        permissions=sorted(p.value for p in ROLE_PERMISSIONS.get(user.role, frozenset())),
    )
