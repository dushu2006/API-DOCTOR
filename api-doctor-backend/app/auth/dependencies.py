from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from app.auth.store import auth_store
from app.auth.schemas import UserResponse


def _extract_token(request: Request, authorization: str | None, x_session_token: str | None) -> str | None:
    if x_session_token:
        return x_session_token.strip()
    if authorization:
        value = authorization.strip()
        if value.lower().startswith("bearer "):
            return value.split(" ", 1)[1].strip()
        return value
    query_token = request.query_params.get("session_token")
    return query_token.strip() if query_token else None


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> UserResponse | None:
    token = _extract_token(request, authorization, x_session_token)
    return auth_store.get_user_by_token(token)


async def require_authenticated_user(user: UserResponse | None = Depends(get_current_user)) -> UserResponse:
    if not user:
        raise HTTPException(401, "Authentication required. Please log in.")
    return user
