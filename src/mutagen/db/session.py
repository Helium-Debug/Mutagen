"""
SQLAlchemy session management for MUTAGEN.

Provides engine creation and session factory.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mutagen.config import get_settings
from mutagen.exceptions import MutagenDatabaseError

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker[Session]] = None


def get_engine() -> Engine:
    """Create or return the SQLAlchemy engine singleton."""
    global _engine
    if _engine is None:
        settings = get_settings()
        if settings.database_url.startswith("sqlite"):
            _engine = create_engine(
                settings.database_url,
                connect_args={"timeout": 30},
                echo=False,
            )
        else:
            connect_args = {
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }
            _engine = create_engine(
                settings.database_url,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=300,
                connect_args=connect_args,
                echo=False,
            )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Create or return the session factory singleton."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        try:
            init_db(engine)
        except Exception:
            pass
        _session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional session scope."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


get_db_context = get_session


def init_db(engine: Optional[Engine] = None) -> None:
    """Create all database tables and apply incremental column migrations."""
    import mutagen.models  # noqa: F401 - ensure models are registered with Base
    from mutagen.db.base import Base

    target_engine = engine or get_engine()
    Base.metadata.create_all(bind=target_engine)

    # For existing PostgreSQL installations, safely ensure added columns exist
    if "postgresql" in str(target_engine.url).lower():
        with target_engine.connect() as conn:
            migration_stmts = [
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE;",
                "ALTER TABLE experiments ADD COLUMN IF NOT EXISTS user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL;",
                "ALTER TABLE memory_records ADD COLUMN IF NOT EXISTS user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE;",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS user_id VARCHAR(36);",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS project_id VARCHAR(36);",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS analysis_id VARCHAR(36);",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS candidate_id VARCHAR(36);",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS generation_number INTEGER;",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS attempt_number INTEGER DEFAULT 1;",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS usage_source VARCHAR(50) DEFAULT 'provider_reported';",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS cached_input_tokens INTEGER DEFAULT 0;",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS estimated_input_tokens INTEGER;",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS estimated_output_tokens INTEGER;",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS estimated_total_tokens INTEGER;",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS request_id VARCHAR(64);",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'success';",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS latency_ms INTEGER DEFAULT 0;",
                "ALTER TABLE ai_usage_records ADD COLUMN IF NOT EXISTS metadata_json JSON;",
                "ALTER TABLE optimization_certificates ADD COLUMN IF NOT EXISTS user_id VARCHAR(36);",
                "ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS user_id VARCHAR(36);",
                "ALTER TABLE mutation_candidates ADD COLUMN IF NOT EXISTS verification_passed BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE mutation_candidates ADD COLUMN IF NOT EXISTS verification_verdict VARCHAR(20);",
                "ALTER TABLE mutation_candidates ADD COLUMN IF NOT EXISTS verification_json JSON;",
                "ALTER TABLE ai_usage_records ALTER COLUMN input_tokens DROP NOT NULL;",
                "ALTER TABLE ai_usage_records ALTER COLUMN output_tokens DROP NOT NULL;",
                "ALTER TABLE ai_usage_records ALTER COLUMN total_tokens DROP NOT NULL;",
            ]
            for stmt in migration_stmts:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
            conn.commit()


def check_database_connection() -> tuple[bool, str]:
    """
    Check if the database is reachable.

    Returns:
        Tuple of (success, message).
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        db_type = "SQLite" if str(engine.url).startswith("sqlite") else "PostgreSQL"
        return True, f"{db_type} connection successful"
    except Exception as e:
        return False, f"Database connection failed: {e}"


def reset_engine() -> None:
    """Reset engine and session factory (used in tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
