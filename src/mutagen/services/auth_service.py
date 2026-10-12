"""
Authentication service for MUTAGEN.

Handles user registration, login with Argon2id, JWT token issuance,
token refresh rotation, logout revocation, and session verification.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from mutagen.config import get_settings
from mutagen.core.auth import (
    create_access_token, decode_access_token, generate_refresh_token,
    hash_password, hash_token, validate_email, validate_password_strength,
    validate_username, verify_password,
)
from mutagen.core.logging import get_logger
from mutagen.db.repositories import AuditRepository, RefreshTokenRepository, UserRepository
from mutagen.db.session import get_session
from mutagen.exceptions import (
    MutagenAuthenticationError, MutagenAuthorizationError, MutagenValidationError,
)

logger = get_logger("services.auth")


class AuthService:
    """Service providing user account authentication and token lifecycle."""

    def register(
        self,
        username: str,
        email: str,
        password: str,
        password_confirm: Optional[str] = None,
    ) -> dict:
        """
        Register a new user account.

        Raises:
            MutagenValidationError: If inputs are invalid or account already exists.
        """
        clean_username = validate_username(username)
        clean_email = validate_email(email)

        if password_confirm is not None and password != password_confirm:
            raise MutagenValidationError("Password and confirmation do not match.")

        validate_password_strength(password)

        with get_session() as session:
            user_repo = UserRepository(session)
            audit = AuditRepository(session)

            # Prevent duplicate username
            if user_repo.find_by_username(clean_username):
                raise MutagenValidationError(f"Username '{clean_username}' is already taken.")

            # Prevent duplicate email
            if user_repo.find_by_email(clean_email):
                raise MutagenValidationError(f"Email '{clean_email}' is already registered.")

            pw_hash = hash_password(password)
            user = user_repo.create(
                username=clean_username,
                email=clean_email,
                password_hash=pw_hash,
                is_active=True,
            )

            audit.log_event(
                event_type="user_registered",
                entity_type="user",
                entity_id=user.id,
                user_id=user.id,
                details={"username": clean_username, "email": clean_email},
            )

            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_active": user.is_active,
                "created_at": str(user.created_at),
            }

    def login(
        self,
        username_or_email: str = "",
        password: str = "",
        identifier: Optional[str] = None,
    ) -> dict:
        """
        Authenticate a user and issue access and refresh tokens.

        Raises:
            MutagenAuthenticationError: If credentials do not match.
        """
        ident = (identifier or username_or_email or "").strip()
        if not ident or not password:
            raise MutagenAuthenticationError("Invalid username/email or password.")

        with get_session() as session:
            user_repo = UserRepository(session)
            rt_repo = RefreshTokenRepository(session)
            audit = AuditRepository(session)

            user = user_repo.find_by_identifier(ident)
            if not user or not user.is_active:
                # Constant-time dummy verification or generic failure message to avoid enumeration
                raise MutagenAuthenticationError("Invalid username/email or password.")

            if not verify_password(password, user.password_hash):
                audit.log_event(
                    event_type="login_failed",
                    entity_type="user",
                    entity_id=user.id,
                    user_id=user.id,
                    details={"identifier": identifier},
                )
                raise MutagenAuthenticationError("Invalid username/email or password.")

            # Create tokens
            access_token = create_access_token(
                user_id=user.id,
                username=user.username,
                email=user.email,
            )

            raw_refresh, token_hash = generate_refresh_token()
            settings = get_settings()
            expires_at = datetime.now(timezone.utc) + timedelta(
                days=settings.jwt_refresh_token_expire_days
            )
            rt_repo.create(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            )

            audit.log_event(
                event_type="user_logged_in",
                entity_type="user",
                entity_id=user.id,
                user_id=user.id,
                details={"username": user.username},
            )

            return {
                "access_token": access_token,
                "token_type": "bearer",
                "refresh_token": raw_refresh,
                "expires_in": settings.jwt_access_token_expire_minutes * 60,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "is_active": user.is_active,
                },
            }

    def refresh(self, raw_refresh_token: str) -> dict:
        """
        Exchange a valid refresh token for a new access token and rotated refresh token.
        """
        if not raw_refresh_token:
            raise MutagenAuthenticationError("Refresh token is required.")

        token_hash = hash_token(raw_refresh_token)

        with get_session() as session:
            rt_repo = RefreshTokenRepository(session)
            user_repo = UserRepository(session)

            token_record = rt_repo.get_active(token_hash)
            if not token_record:
                raise MutagenAuthenticationError("Invalid or revoked refresh token.")

            # Check expiration
            now = datetime.now(timezone.utc)
            if token_record.expires_at.tzinfo is None:
                token_expires = token_record.expires_at.replace(tzinfo=timezone.utc)
            else:
                token_expires = token_record.expires_at

            if token_expires < now:
                token_record.revoked = True
                raise MutagenAuthenticationError("Refresh token has expired. Please log in again.")

            user = user_repo.get(token_record.user_id)
            if not user or not user.is_active:
                raise MutagenAuthenticationError("User account is inactive or not found.")

            # Revoke used refresh token (rotation)
            token_record.revoked = True

            # Generate new tokens
            new_access_token = create_access_token(
                user_id=user.id,
                username=user.username,
                email=user.email,
            )
            new_raw_refresh, new_token_hash = generate_refresh_token()
            settings = get_settings()
            new_expires = now + timedelta(days=settings.jwt_refresh_token_expire_days)
            rt_repo.create(
                user_id=user.id,
                token_hash=new_token_hash,
                expires_at=new_expires,
            )

            return {
                "access_token": new_access_token,
                "token_type": "bearer",
                "refresh_token": new_raw_refresh,
                "expires_in": settings.jwt_access_token_expire_minutes * 60,
            }

    def logout(self, raw_refresh_token: Optional[str] = None, user_id: Optional[str] = None) -> bool:
        """Revoke refresh token(s) upon logout."""
        with get_session() as session:
            rt_repo = RefreshTokenRepository(session)
            audit = AuditRepository(session)

            if raw_refresh_token:
                token_hash = hash_token(raw_refresh_token)
                rt_repo.revoke(token_hash)

            if user_id:
                audit.log_event(
                    event_type="user_logged_out",
                    entity_type="user",
                    entity_id=user_id,
                    user_id=user_id,
                )
            return True

    def get_current_user_from_token(self, access_token: str) -> dict:
        """
        Validate an access token and return the associated active user.

        Raises:
            MutagenAuthenticationError: If token is expired, invalid, or user inactive.
        """
        payload = decode_access_token(access_token)
        user_id = payload["sub"]

        with get_session() as session:
            user_repo = UserRepository(session)
            user = user_repo.get(user_id)
            if not user or not user.is_active:
                raise MutagenAuthenticationError("User account not found or deactivated.")

            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_active": user.is_active,
                "created_at": str(user.created_at),
            }
