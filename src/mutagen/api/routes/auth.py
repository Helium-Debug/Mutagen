"""
Authentication API endpoints for MUTAGEN.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from mutagen.api.deps import get_current_user, get_current_user_optional
from mutagen.exceptions import MutagenAuthenticationError, MutagenValidationError
from mutagen.schemas import (
    RefreshTokenRequest, TokenResponse, UserLoginRequest,
    UserRegisterRequest, UserResponse,
)
from mutagen.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(req: UserRegisterRequest):
    """Register a new user account with secure Argon2id password hashing."""
    svc = AuthService()
    try:
        user = svc.register(
            username=req.username,
            email=req.email,
            password=req.password,
            password_confirm=req.password_confirm,
        )
        return user
    except MutagenValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=TokenResponse)
def login_user(req: UserLoginRequest):
    """Authenticate and obtain JWT access and refresh tokens."""
    svc = AuthService()
    try:
        tokens = svc.login(
            username_or_email=req.login_identifier,
            password=req.password,
        )
        return tokens
    except MutagenAuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(req: RefreshTokenRequest):
    """Exchange a valid refresh token for a new access token."""
    svc = AuthService()
    try:
        tokens = svc.refresh(req.refresh_token)
        return tokens
    except MutagenAuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post("/logout")
def logout_user(
    req: RefreshTokenRequest,
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Revoke refresh token and end session."""
    svc = AuthService()
    user_id = current_user["id"] if current_user else None
    svc.logout(raw_refresh_token=req.refresh_token, user_id=user_id)
    return {"message": "Successfully logged out."}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: dict = Depends(get_current_user)):
    """Get the currently authenticated user's profile."""
    return current_user
