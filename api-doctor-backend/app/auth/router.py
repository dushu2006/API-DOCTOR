from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.auth.dependencies import require_authenticated_user
from app.auth.schemas import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    UpdateProfileRequest,
    UserResponse,
)
from app.auth.store import auth_store

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
async def register(payload: RegisterRequest) -> AuthResponse:
    try:
        user, token = auth_store.register(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return AuthResponse(user=user, session_token=token)


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest) -> AuthResponse:
    try:
        user, token = auth_store.login(payload.identifier, payload.password)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    return AuthResponse(user=user, session_token=token)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    authorization: str | None = Header(default=None),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> MessageResponse:
    token = None
    if x_session_token:
        token = x_session_token
    elif authorization:
        token = authorization.split(" ", 1)[1] if authorization.lower().startswith("bearer ") else authorization
    else:
        token = request.query_params.get("session_token")
    user = auth_store.get_user_by_token(token)
    if user:
        from app.orchestrator import orchestrator

        await orchestrator.reset_current(user.id)
    auth_store.revoke_session(token)
    return MessageResponse(message="Logged out.")


@router.get("/me", response_model=UserResponse)
async def me(user: UserResponse = Depends(require_authenticated_user)) -> UserResponse:
    return user


@router.put("/me", response_model=UserResponse)
async def update_me(payload: UpdateProfileRequest, user: UserResponse = Depends(require_authenticated_user)) -> UserResponse:
    try:
        return auth_store.update_profile(user.id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/change-password", response_model=MessageResponse)
async def change_password(payload: ChangePasswordRequest, user: UserResponse = Depends(require_authenticated_user)) -> MessageResponse:
    try:
        auth_store.change_password(user.id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return MessageResponse(message="Password updated successfully.")


@router.delete("/me", response_model=MessageResponse)
async def delete_me(user: UserResponse = Depends(require_authenticated_user)) -> MessageResponse:
    try:
        from app.orchestrator import orchestrator

        await orchestrator.reset_current(user.id)
        auth_store.delete_account(user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return MessageResponse(message="Account deleted.")
