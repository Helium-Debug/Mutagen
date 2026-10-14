"""
SQLAlchemy ORM models for MUTAGEN.

All persistent entities are defined here with proper relationships,
constraints, indexes, and timestamp tracking. Includes user accounts,
authentication tokens, project files, diffs, and audit events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mutagen.db.base import Base, TimestampMixin


# ── User Account Models ──────────────────────────────────────

class User(TimestampMixin, Base):
    """An individual MUTAGEN user account."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    experiments: Mapped[list["Experiment"]] = relationship(
        back_populates="user"
    )

    __table_args__ = (
        Index("ix_users_username", "username"),
        Index("ix_users_email", "email"),
    )


class RefreshToken(TimestampMixin, Base):
    """Session refresh token record for token rotation and revocation."""
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        Index("ix_refresh_tokens_user", "user_id"),
        Index("ix_refresh_tokens_hash", "token_hash"),
    )


# ── Project & Code Storage ───────────────────────────────────

class Project(TimestampMixin, Base):
    """A MUTAGEN project containing source files and experiments."""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(50), nullable=False, default="python")
    entry_point: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    test_command: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    optimization_objective: Mapped[str] = mapped_column(String(50), default="balanced")
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="projects")
    code_versions: Mapped[list["CodeVersion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    project_files: Mapped[list["ProjectFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    experiments: Mapped[list["Experiment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    memory_records: Mapped[list["MemoryRecord"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_projects_user", "user_id"),
        Index("ix_projects_name", "name"),
        Index("ix_projects_language", "language"),
    )


class ProjectFile(TimestampMixin, Base):
    """A source file tracked inside a project."""
    __tablename__ = "project_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False, default="python")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped["Project"] = relationship(back_populates="project_files")

    __table_args__ = (
        UniqueConstraint("project_id", "file_path", name="uq_project_file_path"),
        Index("ix_project_files_project", "project_id"),
        Index("ix_project_files_hash", "content_hash"),
    )


class CodeVersion(TimestampMixin, Base):
    """An immutable version of a source file within a project."""
    __tablename__ = "code_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    is_original: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(50), nullable=False, default="python")
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="code_versions")

    __table_args__ = (
        Index("ix_code_versions_project", "project_id"),
        Index("ix_code_versions_hash", "content_hash"),
        UniqueConstraint("project_id", "content_hash", name="uq_code_version_hash"),
    )


# ── Experiments & Mutations ──────────────────────────────────

class Experiment(TimestampMixin, Base):
    """An evolution experiment running mutations against source code."""
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    source_file: Mapped[str] = mapped_column(String(500), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    objective: Mapped[str] = mapped_column(String(50), default="balanced")
    status: Mapped[str] = mapped_column(String(50), default="queued")

    # Evolution config
    generations_total: Mapped[int] = mapped_column(Integer, default=5)
    generations_completed: Mapped[int] = mapped_column(Integer, default=0)
    population_size: Mapped[int] = mapped_column(Integer, default=4)
    benchmark_repetitions: Mapped[int] = mapped_column(Integer, default=5)
    execution_timeout: Mapped[int] = mapped_column(Integer, default=30)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=256)
    fitness_weights: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Results
    best_candidate_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    best_improvement_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_candidates: Mapped[int] = mapped_column(Integer, default=0)
    valid_candidates: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="experiments")
    project: Mapped[Optional["Project"]] = relationship(back_populates="experiments")
    generations: Mapped[list["ExperimentGeneration"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    candidates: Mapped[list["MutationCandidate"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    diffs: Mapped[list["SourceDiff"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_experiments_user", "user_id"),
        Index("ix_experiments_status", "status"),
        Index("ix_experiments_project", "project_id"),
        Index("ix_experiments_source_hash", "source_hash"),
    )


class ExperimentGeneration(TimestampMixin, Base):
    """A single generation within an experiment."""
    __tablename__ = "experiment_generations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    candidates_generated: Mapped[int] = mapped_column(Integer, default=0)
    candidates_valid: Mapped[int] = mapped_column(Integer, default=0)
    candidates_tested: Mapped[int] = mapped_column(Integer, default=0)
    best_fitness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    best_candidate_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    memory_context_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    experiment: Mapped["Experiment"] = relationship(back_populates="generations")

    __table_args__ = (
        UniqueConstraint("experiment_id", "generation_number", name="uq_generation"),
        Index("ix_generations_experiment", "experiment_id"),
    )


class MutationCandidate(TimestampMixin, Base):
    """A mutation candidate generated during an experiment."""
    __tablename__ = "mutation_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    generation_number: Mapped[int] = mapped_column(Integer, default=1)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy: Mapped[str] = mapped_column(String(100), default="general")
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expected_improvement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    potential_risks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")

    # Validation
    validation_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_errors: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Testing
    tests_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    test_results_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Benchmarking
    benchmark_results_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    median_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    peak_memory: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Fitness
    fitness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fitness_components: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    speed_improvement: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    memory_improvement: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_eligible: Mapped[bool] = mapped_column(Boolean, default=False)

    # Verification
    verification_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_verdict: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    verification_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    experiment: Mapped["Experiment"] = relationship(back_populates="candidates")
    diffs: Mapped[list["SourceDiff"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_candidates_experiment", "experiment_id"),
        Index("ix_candidates_status", "status"),
        Index("ix_candidates_hash", "content_hash"),
        Index("ix_candidates_fitness", "fitness_score"),
    )


class SourceDiff(TimestampMixin, Base):
    """Persistent storage for candidate source code diffs."""
    __tablename__ = "source_diffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mutation_candidates.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    diff_text: Mapped[str] = mapped_column(Text, nullable=False)
    files_changed: Mapped[int] = mapped_column(Integer, default=1)
    lines_added: Mapped[int] = mapped_column(Integer, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, default=0)
    functions_modified: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    experiment: Mapped["Experiment"] = relationship(back_populates="diffs")
    candidate: Mapped["MutationCandidate"] = relationship(back_populates="diffs")

    __table_args__ = (
        Index("ix_source_diffs_experiment", "experiment_id"),
        Index("ix_source_diffs_candidate", "candidate_id"),
    )


# ── Memory, Auditing & Certificates ──────────────────────────

class MemoryRecord(TimestampMixin, Base):
    """A record in the evolutionary memory system."""
    __tablename__ = "memory_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    project_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    experiment_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    language: Mapped[str] = mapped_column(String(50), default="python")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Relationships
    project: Mapped[Optional["Project"]] = relationship(back_populates="memory_records")

    __table_args__ = (
        Index("ix_memory_user", "user_id"),
        Index("ix_memory_type", "memory_type"),
        Index("ix_memory_project", "project_id"),
        Index("ix_memory_language", "language"),
    )


class AIUsageRecord(TimestampMixin, Base):
    """Tracks AI provider usage for auditing and budgeting."""
    __tablename__ = "ai_usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    experiment_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    analysis_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    candidate_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    generation_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    usage_source: Mapped[str] = mapped_column(String(50), default="provider_reported")
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(50), default="success")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_ai_usage_user", "user_id"),
        Index("ix_ai_usage_project", "project_id"),
        Index("ix_ai_usage_experiment", "experiment_id"),
        Index("ix_ai_usage_analysis", "analysis_id"),
        Index("ix_ai_usage_provider", "provider"),
        Index("ix_ai_usage_operation", "operation"),
        Index("ix_ai_usage_request_id", "request_id"),
    )


class CacheEventRecord(TimestampMixin, Base):
    """Tracks cache events and token optimization savings."""
    __tablename__ = "cache_event_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    analysis_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    experiment_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    cache_type: Mapped[str] = mapped_column(String(50), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ai_requests_avoided: Mapped[int] = mapped_column(Integer, default=1)
    estimated_tokens_avoided: Mapped[int] = mapped_column(Integer, default=0)
    savings_baseline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reused_record_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_cache_event_user", "user_id"),
        Index("ix_cache_event_project", "project_id"),
        Index("ix_cache_event_operation", "operation"),
        Index("ix_cache_event_type", "cache_type"),
        Index("ix_cache_event_hit", "cache_hit"),
    )


class AnalysisCacheRecord(TimestampMixin, Base):
    """Persistent cache for exact and incremental analysis and mutation results."""
    __tablename__ = "analysis_cache_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False, default="python")
    objective: Mapped[str] = mapped_column(String(50), nullable=False, default="balanced")
    symbol_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_analysis_cache_hash", "content_hash"),
        Index("ix_analysis_cache_op", "operation"),
        Index("ix_analysis_cache_user", "user_id"),
        Index("ix_analysis_cache_project", "project_id"),
    )


class OptimizationCertificateRecord(TimestampMixin, Base):
    """Persistent optimization certificate."""
    __tablename__ = "optimization_certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    original_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    certificate_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_certificates_user", "user_id"),
        Index("ix_certificates_experiment", "experiment_id"),
    )


class AuditEvent(TimestampMixin, Base):
    """Audit trail for important actions."""
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_audit_user", "user_id"),
        Index("ix_audit_event_type", "event_type"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )
