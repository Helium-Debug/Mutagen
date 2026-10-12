"""
Tests for MUTAGEN Authentication system.

Covers:
- Successful registration
- Duplicate username & duplicate email rejection
- Successful login
- Incorrect password rejection
- Token validation & expiration
- Logout and refresh token revocation
- Protected endpoint / service enforcement
"""

import pytest
from datetime import timedelta
from mutagen.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_token,
    validate_username,
    validate_email,
)
from mutagen.exceptions import MutagenAuthenticationError, MutagenValidationError
from mutagen.services.auth_service import AuthService


def test_password_hashing_and_verification():
    password = "SuperSecretPassword123!"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_username_and_email_validation():
    # Valid usernames
    assert validate_username("john_doe") == "john_doe"
    assert validate_username("alice123") == "alice123"
    assert validate_username("user-dev") == "user-dev"

    # Invalid usernames
    with pytest.raises(MutagenValidationError):
        validate_username("ab")  # too short
    with pytest.raises(MutagenValidationError):
        validate_username("user!@#")  # invalid chars

    # Valid emails
    assert validate_email("user@example.com") == "user@example.com"
    assert validate_email("first.last@domain.co.uk") == "first.last@domain.co.uk"

    # Invalid emails
    with pytest.raises(MutagenValidationError):
        validate_email("notanemail")
    with pytest.raises(MutagenValidationError):
        validate_email("missing@domain")


def test_jwt_token_creation_and_validation():
    token = create_access_token(
        user_id="user_123",
        username="testuser",
        email="test@example.com",
        expires_minutes=5,
    )
    assert isinstance(token, str)

    payload = decode_access_token(token)
    assert payload["sub"] == "user_123"
    assert payload["username"] == "testuser"
    assert payload["email"] == "test@example.com"


def test_jwt_expired_token_rejection():
    # Token with expired delta
    expired_token = create_access_token(
        user_id="user_123",
        username="testuser",
        email="test@example.com",
        expires_delta=timedelta(seconds=-10),
    )
    with pytest.raises(MutagenAuthenticationError) as exc_info:
        decode_access_token(expired_token)
    assert "expired" in str(exc_info.value).lower()


def test_jwt_invalid_token_rejection():
    with pytest.raises(MutagenAuthenticationError):
        decode_access_token("not.a.valid.jwt.token")


def test_auth_service_registration():
    svc = AuthService()
    user = svc.register(
        username="newuser",
        email="newuser@example.com",
        password="ValidPassword123!",
    )
    assert user["id"] is not None
    assert user["username"] == "newuser"
    assert user["email"] == "newuser@example.com"
    assert "password" not in user
    assert "hashed_password" not in user


def test_auth_service_duplicate_registration_rejection():
    svc = AuthService()
    svc.register(
        username="dupuser",
        email="dup@example.com",
        password="ValidPassword123!",
    )

    # Duplicate username
    with pytest.raises(MutagenValidationError) as exc:
        svc.register(
            username="dupuser",
            email="unique@example.com",
            password="ValidPassword123!",
        )
    assert "already taken" in str(exc.value).lower()

    # Duplicate email
    with pytest.raises(MutagenValidationError) as exc:
        svc.register(
            username="anothername",
            email="dup@example.com",
            password="ValidPassword123!",
        )
    assert "already registered" in str(exc.value).lower()


def test_auth_service_login_success():
    svc = AuthService()
    svc.register(
        username="loginuser",
        email="login@example.com",
        password="SecretPassword123!",
    )

    # Login by username
    res1 = svc.login("loginuser", "SecretPassword123!")
    assert "access_token" in res1
    assert "refresh_token" in res1
    assert res1["user"]["username"] == "loginuser"

    # Login by email
    res2 = svc.login("login@example.com", "SecretPassword123!")
    assert "access_token" in res2
    assert res2["user"]["email"] == "login@example.com"


def test_auth_service_login_failure():
    svc = AuthService()
    svc.register(
        username="targetuser",
        email="target@example.com",
        password="CorrectPassword123!",
    )

    # Wrong password
    with pytest.raises(MutagenAuthenticationError) as exc:
        svc.login("targetuser", "WrongPassword999!")
    assert "invalid" in str(exc.value).lower() and "password" in str(exc.value).lower()

    # Non-existent user
    with pytest.raises(MutagenAuthenticationError) as exc:
        svc.login("nonexistent", "AnyPassword123!")
    # Must not reveal whether account exists
    assert "invalid" in str(exc.value).lower() and "password" in str(exc.value).lower()


def test_auth_service_refresh_token_rotation():
    svc = AuthService()
    svc.register(
        username="refreshuser",
        email="refresh@example.com",
        password="Password123!",
    )
    login_res = svc.login("refreshuser", "Password123!")
    old_refresh_token = login_res["refresh_token"]

    # Refresh tokens
    refreshed = svc.refresh(old_refresh_token)
    assert "access_token" in refreshed
    assert "refresh_token" in refreshed
    new_refresh_token = refreshed["refresh_token"]
    assert new_refresh_token != old_refresh_token

    # Old refresh token should be revoked and unusable
    with pytest.raises(MutagenAuthenticationError):
        svc.refresh(old_refresh_token)


def test_auth_service_logout_and_revocation():
    svc = AuthService()
    svc.register(
        username="logoutuser",
        email="logout@example.com",
        password="Password123!",
    )
    login_res = svc.login("logoutuser", "Password123!")
    refresh_token = login_res["refresh_token"]

    # Logout
    svc.logout(refresh_token)

    # Attempting to refresh with revoked token must fail
    with pytest.raises(MutagenAuthenticationError):
        svc.refresh(refresh_token)
