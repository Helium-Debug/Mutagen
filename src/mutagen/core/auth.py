"""
Authentication and credential management for MUTAGEN.

Provides Argon2id password hashing, JWT access token handling,
refresh token hashing, and secure CLI credential storage.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import jwt

from mutagen.config import get_settings
from mutagen.exceptions import MutagenAuthenticationError, MutagenValidationError

# ── Validation Patterns ──────────────────────────────────────
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
MIN_PASSWORD_LENGTH = 8


# ── Password Hashing ─────────────────────────────────────────

def _get_argon2_hasher():
    try:
        from argon2 import PasswordHasher
        from argon2.profiles import RFC_9106_LOW_MEM
        # RFC 9106 recommended Argon2id parameters
        return PasswordHasher(
            time_cost=3,
            memory_cost=65536,  # 64 MiB
            parallelism=4,
            hash_len=32,
            salt_len=16,
        )
    except ImportError:
        return None


_hasher = _get_argon2_hasher()


def hash_password(password: str) -> str:
    """
    Hash a password using Argon2id with secure defaults.
    Falls back to PBKDF2-HMAC-SHA256 if Argon2 is unavailable.
    """
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise MutagenValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )

    if _hasher is not None:
        return _hasher.hash(password)

    # Secure fallback: PBKDF2-HMAC-SHA256 with 600,000 iterations
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        600_000,
    )
    return f"pbkdf2:sha256:600000${salt}${dk.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a stored hash."""
    if not plain_password or not hashed_password:
        return False

    if hashed_password.startswith("$argon2"):
        if _hasher is not None:
            try:
                return _hasher.verify(hashed_password, plain_password)
            except Exception:
                return False
        return False

    if hashed_password.startswith("pbkdf2:sha256:"):
        try:
            parts = hashed_password.split("$")
            if len(parts) != 3:
                return False
            _, salt, expected_hex = parts
            dk = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode("utf-8"),
                salt.encode("utf-8"),
                600_000,
            )
            return secrets.compare_digest(dk.hex(), expected_hex)
        except Exception:
            return False

    return False


def validate_username(username: str) -> str:
    """Validate username format."""
    clean = (username or "").strip()
    if not USERNAME_REGEX.match(clean):
        raise MutagenValidationError(
            "Username must be 3-32 characters long and contain only "
            "alphanumeric characters, underscores, and hyphens."
        )
    return clean


def validate_email(email: str) -> str:
    """Validate email address format."""
    clean = (email or "").strip().lower()
    if not EMAIL_REGEX.match(clean):
        raise MutagenValidationError("Invalid email address format.")
    return clean


def validate_password_strength(password: str) -> None:
    """Validate password meets minimum security criteria."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise MutagenValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )


# ── Tokens (JWT & Refresh) ───────────────────────────────────

def create_access_token(
    user_id: str,
    username: str,
    email: str,
    expires_delta: Optional[timedelta] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    """Create a signed JWT access token."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    elif expires_minutes is not None:
        expire = now + timedelta(minutes=expires_minutes)
    else:
        expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload = {
        "sub": user_id,
        "username": username,
        "email": email,
        "exp": expire,
        "iat": now,
        "jti": secrets.token_hex(16),
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT access token.

    Raises:
        MutagenAuthenticationError: If the token is invalid, expired, or malformed.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != "access":
            raise MutagenAuthenticationError("Invalid token type.")
        if not payload.get("sub"):
            raise MutagenAuthenticationError("Token missing subject identifier.")
        return payload
    except jwt.ExpiredSignatureError:
        raise MutagenAuthenticationError("Session token has expired. Please log in again.")
    except jwt.InvalidTokenError as e:
        raise MutagenAuthenticationError(f"Invalid authentication token: {e}")


def generate_refresh_token() -> tuple[str, str]:
    """
    Generate a cryptographically secure refresh token.

    Returns:
        tuple of (raw_token, token_hash)
        Only token_hash should be stored in the database.
    """
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_token(raw_token)
    return raw_token, token_hash


def hash_token(raw_token: str) -> str:
    """Compute SHA-256 hash of a token string for safe lookup."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# ── CLI Credentials Storage ──────────────────────────────────

class CredentialsManager:
    """
    Manages local CLI session credentials.

    Stores the current access token and refresh token in a user-private
    credentials file (~/.mutagen/credentials.json).
    """

    @classmethod
    def get_credentials_path(cls) -> Path:
        settings = get_settings()
        if settings.credentials_path:
            return Path(settings.credentials_path).resolve()
        return Path.home() / ".mutagen" / "credentials.json"

    @classmethod
    def save(
        cls,
        user_id: str,
        username: str,
        email: str,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> None:
        """Save user credentials securely to disk."""
        path = cls.get_credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "user_id": user_id,
            "username": username,
            "email": email,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        # Write file atomically with restricted permissions where supported
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Restrict permissions on Unix-like systems
        try:
            if hasattr(os, "chmod"):
                os.chmod(temp_path, 0o600)
        except Exception:
            pass

        temp_path.replace(path)

    @classmethod
    def load(cls) -> Optional[dict[str, Any]]:
        """Load stored credentials from disk if present."""
        path = cls.get_credentials_path()
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict) or "access_token" not in data:
                return None
            return data
        except Exception:
            return None

    @classmethod
    def clear(cls) -> bool:
        """Remove stored credentials on logout."""
        path = cls.get_credentials_path()
        if path.exists():
            try:
                path.unlink()
                return True
            except Exception:
                return False
        return False
