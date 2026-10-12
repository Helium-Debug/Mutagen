"""
Identifier generation for MUTAGEN entities.

Provides consistent UUID-based identifiers with optional prefixes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def generate_id() -> str:
    """Generate a new UUID4 identifier."""
    return str(uuid.uuid4())


def generate_short_id() -> str:
    """Generate a short 8-character identifier (first segment of UUID4)."""
    return str(uuid.uuid4()).split("-")[0]


def generate_experiment_id() -> str:
    """Generate a prefixed experiment identifier."""
    return f"exp-{generate_short_id()}"


def generate_mutation_id() -> str:
    """Generate a prefixed mutation identifier."""
    return f"mut-{generate_short_id()}"


def generate_project_id() -> str:
    """Generate a prefixed project identifier."""
    return f"prj-{generate_short_id()}"


def utc_now() -> datetime:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc)
