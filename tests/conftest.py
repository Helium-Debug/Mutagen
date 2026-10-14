"""
Pytest configuration and shared fixtures for MUTAGEN tests.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from mutagen.config import MutagenSettings, AIProvider, OptimizationObjective, reset_settings
from mutagen.db.base import Base
from mutagen.db.session import reset_engine
from mutagen.ai.fake_provider import FakeProvider
from mutagen.sandbox.docker_manager import DockerSandbox, SandboxResult


@pytest.fixture(autouse=True)
def test_environment(tmp_path, monkeypatch):
    """Configure environment for isolated testing with in-memory DB and fake AI."""
    db_file = tmp_path / "test_mutagen.db"
    db_url = f"sqlite:///{db_file}"
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    creds_file = tmp_path / "credentials.json"
    monkeypatch.setenv("MUTAGEN_DATABASE_URL", db_url)
    monkeypatch.setenv("MUTAGEN_AI_PROVIDER", "fake")
    monkeypatch.setenv("MUTAGEN_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("MUTAGEN_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("MUTAGEN_CREDENTIALS_PATH", str(creds_file))

    reset_settings()
    reset_engine()

    # Create tables in the test database
    import mutagen.models  # noqa: F401
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)

    yield

    reset_engine()
    reset_settings()


@pytest.fixture
def auth_user(test_environment, tmp_path):
    """Provide a registered and logged-in user with CLI credentials saved."""
    from mutagen.services.auth_service import AuthService
    from mutagen.core.auth import CredentialsManager

    auth_svc = AuthService()
    user = auth_svc.register(
        username="alice",
        email="alice@example.com",
        password="SecurePassword123!",
    )
    tokens = auth_svc.login(identifier="alice", password="SecurePassword123!")
    CredentialsManager.save(
        user_id=user["id"],
        username=user["username"],
        email=user["email"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
    )
    return {
        "user": user,
        "tokens": tokens,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
    }


@pytest.fixture
def db_session(tmp_path):
    """Provide a direct SQLAlchemy test session."""
    db_file = tmp_path / "test_mutagen.db"
    import mutagen.models  # noqa: F401
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def fake_ai():
    """Provide a FakeProvider instance."""
    return FakeProvider()


@pytest.fixture
def mock_sandbox(mocker):
    """Provide a mocked DockerSandbox that returns deterministic results."""
    sandbox = mocker.MagicMock(spec=DockerSandbox)
    sandbox.execute_python.return_value = SandboxResult(
        exit_code=0,
        stdout='{"exit_code": 0, "output": "Execution successful", "benchmark_time": 0.005}',
        stderr="",
        duration_seconds=0.005,
        timed_out=False,
        oom_killed=False,
    )
    sandbox.check_availability.return_value = (True, "Docker mock active")
    sandbox.check_image.return_value = (True, "Image mock active")
    return sandbox


@pytest.fixture
def sample_python_code():
    """Sample Python function for testing."""
    return '''def compute_sum(numbers: list[int]) -> int:
    """Compute the sum of numbers."""
    total = 0
    for num in numbers:
        total += num
    return total
'''


@pytest.fixture
def sample_fibonacci_code():
    """Sample recursive Fibonacci."""
    return '''def fibonacci(n: int) -> int:
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 2)
'''
