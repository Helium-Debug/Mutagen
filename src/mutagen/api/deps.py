"""
FastAPI dependency injection utilities for MUTAGEN API.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from mutagen.exceptions import MutagenAuthenticationError
from mutagen.services.auth_service import AuthService

security_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> dict:
    """
    Dependency to require and validate Bearer authentication token.

    Returns:
        dict representing authenticated user.

    Raises:
        HTTPException 401: If unauthenticated, token expired, or token invalid.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in before analyzing, testing, or optimizing code.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    auth_svc = AuthService()
    try:
        user = auth_svc.get_current_user_from_token(credentials.credentials)
        return user
    except MutagenAuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> Optional[dict]:
    """Optional Bearer authentication dependency."""
    if not credentials or not credentials.credentials:
        return None
    auth_svc = AuthService()
    try:
        return auth_svc.get_current_user_from_token(credentials.credentials)
    except MutagenAuthenticationError:
        return None

