"""Authentication endpoints.

Thin handlers: validate input, throttle where relevant, call :class:`AuthService`, serialize. The
refresh token is returned in the body and also set as an httpOnly cookie so browser clients never
touch it in JS; API clients can use the body value.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import (
    AuthServiceDep,
    AuthThrottleDep,
    CurrentUser,
    client_ip,
)
from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.schemas.auth import (
    EmailVerificationRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth import IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=raw,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        max_age=settings.refresh_token_ttl_seconds,
        path="/auth",
    )


def _token_response(response: Response, tokens: IssuedTokens) -> TokenResponse:
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        refresh_token=tokens.refresh_token,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, service: AuthServiceDep) -> UserResponse:
    user = await service.register(
        email=payload.email, password=payload.password, full_name=payload.full_name
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    throttle: AuthThrottleDep,
) -> TokenResponse:
    await throttle.check(f"{client_ip(request)}:{payload.email.lower()}")
    user = await service.authenticate(email=payload.email, password=payload.password)
    tokens = await service.issue_tokens(user)
    return _token_response(response, tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> TokenResponse:
    raw = payload.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise AuthenticationError("No refresh token provided.")
    tokens = await service.rotate(raw)
    return _token_response(response, tokens)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> MessageResponse:
    raw = payload.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if raw:
        await service.logout(raw)
    response.delete_cookie(REFRESH_COOKIE, path="/auth")
    return MessageResponse(message="Logged out.")


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    payload: EmailVerificationRequest, service: AuthServiceDep
) -> MessageResponse:
    await service.verify_email(payload.token)
    return MessageResponse(message="Email verified.")


@router.post("/password-reset", response_model=MessageResponse)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    service: AuthServiceDep,
    throttle: AuthThrottleDep,
) -> MessageResponse:
    await throttle.check(f"{client_ip(request)}:reset")
    await service.request_password_reset(payload.email)
    # Always the same response, regardless of whether the email exists.
    return MessageResponse(message="If the email exists, a reset link has been sent.")


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    payload: PasswordResetConfirm, service: AuthServiceDep
) -> MessageResponse:
    await service.reset_password(payload.token, payload.new_password)
    return MessageResponse(message="Password has been reset.")
