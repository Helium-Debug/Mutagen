"""
Database repository layer for MUTAGEN.

Provides CRUD operations and access control isolation for all persistent entities.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, desc, func, or_, and_, case
from sqlalchemy.orm import Session

from mutagen.core.identifiers import generate_id, generate_mutation_id, utc_now
from mutagen.models import (
    User, RefreshToken, Project, ProjectFile, CodeVersion, Experiment,
    ExperimentGeneration, MutationCandidate, SourceDiff, MemoryRecord,
    AIUsageRecord, OptimizationCertificateRecord, AuditEvent,
    CacheEventRecord, AnalysisCacheRecord,
)


class UserRepository:
    """Repository for User entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        username: str,
        email: str,
        password_hash: str,
        is_active: bool = True,
        id: Optional[str] = None,
    ) -> User:
        user = User(
            id=id or generate_id(),
            username=username,
            email=email.lower(),
            password_hash=password_hash,
            is_active=is_active,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get(self, user_id: str) -> Optional[User]:
        return self.session.get(User, user_id)

    def find_by_username(self, username: str) -> Optional[User]:
        stmt = select(User).where(func.lower(User.username) == username.lower())
        return self.session.execute(stmt).scalar_one_or_none()

    def find_by_email(self, email: str) -> Optional[User]:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        return self.session.execute(stmt).scalar_one_or_none()

    def find_by_identifier(self, identifier: str) -> Optional[User]:
        """Find user by either username or email."""
        clean = identifier.strip().lower()
        stmt = select(User).where(
            or_(
                func.lower(User.username) == clean,
                func.lower(User.email) == clean,
            )
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def count(self) -> int:
        stmt = select(func.count(User.id))
        return self.session.execute(stmt).scalar_one() or 0


class RefreshTokenRepository:
    """Repository for refresh token management."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: str, token_hash: str, expires_at) -> RefreshToken:
        rt = RefreshToken(
            id=generate_id(),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked=False,
        )
        self.session.add(rt)
        self.session.flush()
        return rt

    def get_active(self, token_hash: str) -> Optional[RefreshToken]:
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def revoke(self, token_hash: str) -> bool:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        rt = self.session.execute(stmt).scalar_one_or_none()
        if rt:
            rt.revoked = True
            self.session.flush()
            return True
        return False

    def revoke_all_for_user(self, user_id: str) -> int:
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
        )
        tokens = list(self.session.execute(stmt).scalars().all())
        for t in tokens:
            t.revoked = True
        self.session.flush()
        return len(tokens)


class ProjectRepository:
    """Repository for Project CRUD operations with user-level isolation."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> Project:
        project = Project(id=kwargs.pop("id", generate_id()), **kwargs)
        self.session.add(project)
        self.session.flush()
        return project

    def get(self, project_id: str, user_id: Optional[str] = None) -> Optional[Project]:
        project = self.session.get(Project, project_id)
        if not project:
            return None
        if user_id and project.user_id and project.user_id != user_id:
            return None
        return project

    def list_all(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Project]:
        stmt = select(Project)
        if user_id:
            stmt = stmt.where(Project.user_id == user_id)
        stmt = stmt.order_by(desc(Project.created_at)).limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars().all())

    def delete(self, project_id: str, user_id: Optional[str] = None) -> bool:
        project = self.get(project_id, user_id=user_id)
        if project:
            self.session.delete(project)
            self.session.flush()
            return True
        return False

    def find_by_name(self, name: str, user_id: Optional[str] = None) -> Optional[Project]:
        stmt = select(Project).where(Project.name == name)
        if user_id:
            stmt = stmt.where(Project.user_id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()


class ProjectFileRepository:
    """Repository for ProjectFile entities."""

    def __init__(self, session: Session):
        self.session = session

    def upsert(
        self,
        project_id: str,
        file_path: str,
        content: str,
        content_hash: str,
        language: str = "python",
        size_bytes: int = 0,
    ) -> ProjectFile:
        stmt = select(ProjectFile).where(
            ProjectFile.project_id == project_id,
            ProjectFile.file_path == file_path,
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        if existing:
            existing.content = content
            existing.content_hash = content_hash
            existing.language = language
            existing.size_bytes = size_bytes or len(content.encode("utf-8"))
            self.session.flush()
            return existing

        pf = ProjectFile(
            id=generate_id(),
            project_id=project_id,
            file_path=file_path,
            content=content,
            content_hash=content_hash,
            language=language,
            size_bytes=size_bytes or len(content.encode("utf-8")),
        )
        self.session.add(pf)
        self.session.flush()
        return pf

    def list_for_project(self, project_id: str) -> list[ProjectFile]:
        stmt = select(ProjectFile).where(ProjectFile.project_id == project_id)
        return list(self.session.execute(stmt).scalars().all())

    def get(self, project_id: str, file_path: str) -> Optional[ProjectFile]:
        stmt = select(ProjectFile).where(
            ProjectFile.project_id == project_id,
            ProjectFile.file_path == file_path,
        )
        return self.session.execute(stmt).scalar_one_or_none()


class CodeVersionRepository:
    """Repository for CodeVersion CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> CodeVersion:
        cv = CodeVersion(id=kwargs.pop("id", generate_id()), **kwargs)
        self.session.add(cv)
        self.session.flush()
        return cv

    def get(self, version_id: str) -> Optional[CodeVersion]:
        return self.session.get(CodeVersion, version_id)

    def get_by_hash(self, project_id: str, content_hash: str) -> Optional[CodeVersion]:
        stmt = select(CodeVersion).where(
            CodeVersion.project_id == project_id,
            CodeVersion.content_hash == content_hash,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_for_project(self, project_id: str) -> list[CodeVersion]:
        stmt = (
            select(CodeVersion)
            .where(CodeVersion.project_id == project_id)
            .order_by(CodeVersion.version_number)
        )
        return list(self.session.execute(stmt).scalars().all())


class ExperimentRepository:
    """Repository for Experiment CRUD operations with user isolation."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> Experiment:
        exp = Experiment(id=kwargs.pop("id", generate_id()), **kwargs)
        self.session.add(exp)
        self.session.flush()
        return exp

    def get(self, experiment_id: str, user_id: Optional[str] = None) -> Optional[Experiment]:
        exp = self.session.get(Experiment, experiment_id)
        if not exp:
            return None
        if user_id and exp.user_id and exp.user_id != user_id:
            return None
        return exp

    def list_all(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Experiment]:
        stmt = select(Experiment)
        if user_id:
            stmt = stmt.where(Experiment.user_id == user_id)
        stmt = stmt.order_by(desc(Experiment.created_at)).limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars().all())

    def list_for_project(
        self,
        project_id: str,
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[Experiment]:
        stmt = select(Experiment).where(Experiment.project_id == project_id)
        if user_id:
            stmt = stmt.where(Experiment.user_id == user_id)
        stmt = stmt.order_by(desc(Experiment.created_at)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def update_status(
        self,
        experiment_id: str,
        status: str,
        error_message: Optional[str] = None,
        **kwargs,
    ) -> Optional[Experiment]:
        exp = self.get(experiment_id)
        if exp:
            exp.status = status
            if error_message:
                exp.error_message = error_message
            for k, v in kwargs.items():
                if hasattr(exp, k):
                    setattr(exp, k, v)
            self.session.flush()
        return exp

    def update_results(
        self,
        experiment_id: str,
        best_candidate_id: Optional[str] = None,
        best_improvement_percent: Optional[float] = None,
        duration_seconds: Optional[float] = None,
        total_candidates: Optional[int] = None,
        valid_candidates: Optional[int] = None,
    ) -> Optional[Experiment]:
        exp = self.get(experiment_id)
        if exp:
            if best_candidate_id:
                exp.best_candidate_id = best_candidate_id
            if best_improvement_percent is not None:
                exp.best_improvement_percent = best_improvement_percent
            if duration_seconds is not None:
                exp.duration_seconds = duration_seconds
            if total_candidates is not None:
                exp.total_candidates = total_candidates
            if valid_candidates is not None:
                exp.valid_candidates = valid_candidates
            self.session.flush()
        return exp


class GenerationRepository:
    """Repository for ExperimentGeneration operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> ExperimentGeneration:
        gen = ExperimentGeneration(id=kwargs.pop("id", generate_id()), **kwargs)
        self.session.add(gen)
        self.session.flush()
        return gen

    def list_for_experiment(self, experiment_id: str) -> list[ExperimentGeneration]:
        stmt = (
            select(ExperimentGeneration)
            .where(ExperimentGeneration.experiment_id == experiment_id)
            .order_by(ExperimentGeneration.generation_number)
        )
        return list(self.session.execute(stmt).scalars().all())


class CandidateRepository:
    """Repository for MutationCandidate operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> MutationCandidate:
        cand_id = kwargs.pop("id", None) or generate_mutation_id()
        if self.session.get(MutationCandidate, cand_id) is not None:
            cand_id = generate_mutation_id()
        candidate = MutationCandidate(id=cand_id, **kwargs)
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def get(self, candidate_id: str) -> Optional[MutationCandidate]:
        return self.session.get(MutationCandidate, candidate_id)

    def get_for_user(self, candidate_id: str, user_id: Optional[str] = None) -> Optional[MutationCandidate]:
        cand = self.session.get(MutationCandidate, candidate_id)
        if not cand:
            return None
        if user_id:
            exp = self.session.get(Experiment, cand.experiment_id)
            if exp and exp.user_id and exp.user_id != user_id:
                return None
        return cand

    def list_for_experiment(self, experiment_id: str) -> list[MutationCandidate]:
        stmt = (
            select(MutationCandidate)
            .where(MutationCandidate.experiment_id == experiment_id)
            .order_by(desc(MutationCandidate.fitness_score))
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_best_eligible(self, experiment_id: str) -> Optional[MutationCandidate]:
        stmt = (
            select(MutationCandidate)
            .where(
                MutationCandidate.experiment_id == experiment_id,
                MutationCandidate.is_eligible.is_(True),
            )
            .order_by(desc(MutationCandidate.fitness_score))
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def update_status(
        self,
        candidate_id: str,
        status: str,
        **kwargs,
    ) -> Optional[MutationCandidate]:
        try:
            cand = self.get(candidate_id)
            if cand:
                cand.status = status
                for k, v in kwargs.items():
                    if hasattr(cand, k):
                        setattr(cand, k, v)
                self.session.flush()
            return cand
        except Exception as e:
            logger.warning(
                f"Failed to flush candidate {candidate_id} status ({e}); retrying with recovered connection."
            )
            try:
                self.session.rollback()
            except Exception:
                pass
            cand = self.get(candidate_id)
            if cand:
                cand.status = status
                for k, v in kwargs.items():
                    if hasattr(cand, k):
                        setattr(cand, k, v)
                self.session.flush()
            return cand

    def update_results(
        self,
        candidate_id: str,
        **kwargs,
    ) -> Optional[MutationCandidate]:
        try:
            cand = self.get(candidate_id)
            if cand:
                for k, v in kwargs.items():
                    if hasattr(cand, k):
                        setattr(cand, k, v)
                self.session.flush()
            return cand
        except Exception as e:
            logger.warning(
                f"Failed to flush candidate {candidate_id} results ({e}); retrying with recovered connection."
            )
            try:
                self.session.rollback()
            except Exception:
                pass
            cand = self.get(candidate_id)
            if cand:
                for k, v in kwargs.items():
                    if hasattr(cand, k):
                        setattr(cand, k, v)
                self.session.flush()
            return cand



class SourceDiffRepository:
    """Repository for SourceDiff persistent records."""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        experiment_id: str,
        candidate_id: str,
        diff_text: str,
        file_path: str = "",
        files_changed: int = 1,
        lines_added: int = 0,
        lines_removed: int = 0,
        functions_modified: int = 0,
        summary_json: Optional[dict] = None,
    ) -> SourceDiff:
        diff = SourceDiff(
            id=generate_id(),
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            file_path=file_path,
            diff_text=diff_text,
            files_changed=files_changed,
            lines_added=lines_added,
            lines_removed=lines_removed,
            functions_modified=functions_modified,
            summary_json=summary_json,
        )
        self.session.add(diff)
        self.session.flush()
        return diff

    def get_for_candidate(self, candidate_id: str) -> Optional[SourceDiff]:
        stmt = select(SourceDiff).where(SourceDiff.candidate_id == candidate_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_for_experiment(self, experiment_id: str) -> list[SourceDiff]:
        stmt = select(SourceDiff).where(SourceDiff.experiment_id == experiment_id)
        return list(self.session.execute(stmt).scalars().all())


class MemoryRepository:
    """Repository for evolutionary memory with user isolation."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> MemoryRecord:
        record = MemoryRecord(id=kwargs.pop("id", generate_id()), **kwargs)
        self.session.add(record)
        self.session.flush()
        return record

    def search(
        self,
        memory_type: Optional[str] = None,
        project_id: Optional[str] = None,
        language: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        stmt = select(MemoryRecord)
        if user_id:
            stmt = stmt.where(or_(MemoryRecord.user_id == user_id, MemoryRecord.user_id.is_(None)))
        if memory_type:
            stmt = stmt.where(MemoryRecord.memory_type == memory_type)
        if project_id:
            stmt = stmt.where(MemoryRecord.project_id == project_id)
        if language:
            stmt = stmt.where(MemoryRecord.language == language)
        stmt = stmt.order_by(desc(MemoryRecord.relevance_score)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def search_by_content(
        self,
        query: str,
        user_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Basic text search against memory content with user isolation."""
        stmt = select(MemoryRecord).where(MemoryRecord.content.ilike(f"%{query}%"))
        if user_id:
            stmt = stmt.where(or_(MemoryRecord.user_id == user_id, MemoryRecord.user_id.is_(None)))
        stmt = stmt.order_by(desc(MemoryRecord.relevance_score)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def count_by_type(self, user_id: Optional[str] = None) -> dict[str, int]:
        stmt = select(MemoryRecord.memory_type, func.count(MemoryRecord.id))
        if user_id:
            stmt = stmt.where(or_(MemoryRecord.user_id == user_id, MemoryRecord.user_id.is_(None)))
        stmt = stmt.group_by(MemoryRecord.memory_type)
        results = self.session.execute(stmt).all()
        return {row[0]: row[1] for row in results}

    def delete_for_project(self, project_id: str) -> int:
        records = self.search(project_id=project_id, limit=10000)
        count = len(records)
        for r in records:
            self.session.delete(r)
        self.session.flush()
        return count


class AIUsageRepository:
    """Repository for AI usage tracking and token metrics."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> AIUsageRecord:
        request_id = kwargs.get("request_id")
        if request_id:
            existing = self.get_by_request_id(request_id)
            if existing:
                return existing

        # Sync legacy & new status/latency fields
        if "duration_ms" in kwargs and "latency_ms" not in kwargs:
            kwargs["latency_ms"] = kwargs["duration_ms"]
        elif "latency_ms" in kwargs and "duration_ms" not in kwargs:
            kwargs["duration_ms"] = kwargs["latency_ms"]

        if "status" in kwargs and "success" not in kwargs:
            kwargs["success"] = (kwargs["status"] == "success")
        elif "success" in kwargs and "status" not in kwargs:
            kwargs["status"] = "success" if kwargs["success"] else "failed"

        # Safe defaults for required non-null string fields
        if not kwargs.get("provider"):
            kwargs["provider"] = "default"
        if not kwargs.get("model"):
            kwargs["model"] = "default"
        if not kwargs.get("operation"):
            kwargs["operation"] = "general"

        record = AIUsageRecord(id=kwargs.pop("id", generate_id()), **kwargs)
        self.session.add(record)
        self.session.flush()
        return record

    def record_usage(self, **kwargs) -> AIUsageRecord:
        """Alias for create to support standard usage tracking nomenclature."""
        return self.create(**kwargs)

    def get_by_request_id(self, request_id: str) -> Optional[AIUsageRecord]:
        stmt = select(AIUsageRecord).where(AIUsageRecord.request_id == request_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def query_records(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AIUsageRecord]:
        stmt = select(AIUsageRecord)
        if user_id:
            stmt = stmt.where(or_(AIUsageRecord.user_id == user_id, AIUsageRecord.user_id.is_(None)))
        if project_id:
            stmt = stmt.where(AIUsageRecord.project_id == project_id)
        if since:
            stmt = stmt.where(AIUsageRecord.created_at >= since)
        if until:
            stmt = stmt.where(AIUsageRecord.created_at <= until)
        if operation:
            stmt = stmt.where(func.lower(AIUsageRecord.operation) == operation.lower())
        if provider:
            stmt = stmt.where(func.lower(AIUsageRecord.provider) == provider.lower())
        if model:
            stmt = stmt.where(func.lower(AIUsageRecord.model) == model.lower())
        if status:
            stmt = stmt.where(func.lower(AIUsageRecord.status) == status.lower())

        stmt = stmt.order_by(desc(AIUsageRecord.created_at)).offset(offset).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def count_records(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(AIUsageRecord.id))
        if user_id:
            stmt = stmt.where(or_(AIUsageRecord.user_id == user_id, AIUsageRecord.user_id.is_(None)))
        if project_id:
            stmt = stmt.where(AIUsageRecord.project_id == project_id)
        if since:
            stmt = stmt.where(AIUsageRecord.created_at >= since)
        if until:
            stmt = stmt.where(AIUsageRecord.created_at <= until)
        if operation:
            stmt = stmt.where(func.lower(AIUsageRecord.operation) == operation.lower())
        if provider:
            stmt = stmt.where(func.lower(AIUsageRecord.provider) == provider.lower())
        if model:
            stmt = stmt.where(func.lower(AIUsageRecord.model) == model.lower())
        if status:
            stmt = stmt.where(func.lower(AIUsageRecord.status) == status.lower())

        return self.session.execute(stmt).scalar() or 0

    def aggregate_usage(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        stmt = select(
            func.count(AIUsageRecord.id).label("total_requests"),
            func.sum(
                case(
                    (or_(AIUsageRecord.status == "success", AIUsageRecord.success.is_(True)), 1),
                    else_=0,
                )
            ).label("successful_requests"),
            func.sum(
                case(
                    (or_(AIUsageRecord.status == "failed", AIUsageRecord.success.is_(False)), 1),
                    else_=0,
                )
            ).label("failed_requests"),
            func.sum(
                case(
                    (AIUsageRecord.usage_source == "provider_reported", AIUsageRecord.input_tokens),
                    else_=0,
                )
            ).label("actual_input_tokens"),
            func.sum(
                case(
                    (AIUsageRecord.usage_source == "provider_reported", AIUsageRecord.output_tokens),
                    else_=0,
                )
            ).label("actual_output_tokens"),
            func.sum(
                case(
                    (AIUsageRecord.usage_source == "provider_reported", AIUsageRecord.total_tokens),
                    else_=0,
                )
            ).label("actual_total_tokens"),
            func.sum(AIUsageRecord.cached_input_tokens).label("cached_input_tokens"),
            func.sum(
                case(
                    (AIUsageRecord.usage_source == "estimated", AIUsageRecord.estimated_total_tokens),
                    else_=0,
                )
            ).label("estimated_total_tokens"),
            func.sum(
                case(
                    (
                        or_(
                            AIUsageRecord.usage_source == "unavailable",
                            AIUsageRecord.total_tokens.is_(None),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("unavailable_measurements"),
        )

        if user_id:
            stmt = stmt.where(or_(AIUsageRecord.user_id == user_id, AIUsageRecord.user_id.is_(None)))
        if project_id:
            stmt = stmt.where(AIUsageRecord.project_id == project_id)
        if since:
            stmt = stmt.where(AIUsageRecord.created_at >= since)
        if until:
            stmt = stmt.where(AIUsageRecord.created_at <= until)
        if operation:
            stmt = stmt.where(func.lower(AIUsageRecord.operation) == operation.lower())
        if provider:
            stmt = stmt.where(func.lower(AIUsageRecord.provider) == provider.lower())
        if model:
            stmt = stmt.where(func.lower(AIUsageRecord.model) == model.lower())

        row = self.session.execute(stmt).one()
        return {
            "total_requests": row[0] or 0,
            "successful_requests": row[1] or 0,
            "failed_requests": row[2] or 0,
            "actual_input_tokens": row[3] or 0,
            "actual_output_tokens": row[4] or 0,
            "actual_total_tokens": row[5] or 0,
            "cached_input_tokens": row[6] or 0,
            "estimated_total_tokens": row[7] or 0,
            "unavailable_measurements": row[8] or 0,
        }

    def total_for_experiment(self, experiment_id: str) -> dict[str, int]:
        stmt = (
            select(
                func.sum(AIUsageRecord.input_tokens),
                func.sum(AIUsageRecord.output_tokens),
                func.sum(AIUsageRecord.total_tokens),
                func.count(AIUsageRecord.id),
            )
            .where(AIUsageRecord.experiment_id == experiment_id)
        )
        row = self.session.execute(stmt).one()
        return {
            "input_tokens": row[0] or 0,
            "output_tokens": row[1] or 0,
            "total_tokens": row[2] or 0,
            "requests": row[3] or 0,
        }


class CacheEventRepository:
    """Repository for cache event tracking and optimization savings."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> CacheEventRecord:
        # Prevent duplicate savings for identical analysis & reused record
        reused_record_id = kwargs.get("reused_record_id")
        analysis_id = kwargs.get("analysis_id")
        operation = kwargs.get("operation")
        if reused_record_id and analysis_id and operation:
            existing = self.find_existing(analysis_id, reused_record_id, operation)
            if existing:
                return existing

        record = CacheEventRecord(id=kwargs.pop("id", generate_id()), **kwargs)
        self.session.add(record)
        self.session.flush()
        return record

    def find_existing(
        self,
        analysis_id: str,
        reused_record_id: str,
        operation: str,
    ) -> Optional[CacheEventRecord]:
        stmt = select(CacheEventRecord).where(
            CacheEventRecord.analysis_id == analysis_id,
            CacheEventRecord.reused_record_id == reused_record_id,
            CacheEventRecord.operation == operation,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def aggregate_cache_stats(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
    ) -> dict[str, Any]:
        stmt = select(
            func.count(CacheEventRecord.id).label("total_lookups"),
            func.sum(
                case((CacheEventRecord.cache_hit.is_(True), 1), else_=0)
            ).label("cache_hits"),
            func.sum(
                case((CacheEventRecord.cache_hit.is_(False), 1), else_=0)
            ).label("cache_misses"),
            func.sum(
                case(
                    (
                        and_(
                            CacheEventRecord.cache_hit.is_(True),
                            CacheEventRecord.cache_type == "incremental_analysis",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("incremental_analyses"),
            func.sum(
                case(
                    (CacheEventRecord.cache_hit.is_(True), CacheEventRecord.ai_requests_avoided),
                    else_=0,
                )
            ).label("ai_requests_avoided"),
            func.sum(
                case(
                    (CacheEventRecord.cache_hit.is_(True), CacheEventRecord.estimated_tokens_avoided),
                    else_=0,
                )
            ).label("estimated_tokens_saved"),
        )

        if user_id:
            stmt = stmt.where(or_(CacheEventRecord.user_id == user_id, CacheEventRecord.user_id.is_(None)))
        if project_id:
            stmt = stmt.where(CacheEventRecord.project_id == project_id)
        if since:
            stmt = stmt.where(CacheEventRecord.created_at >= since)
        if until:
            stmt = stmt.where(CacheEventRecord.created_at <= until)
        if operation:
            stmt = stmt.where(func.lower(CacheEventRecord.operation) == operation.lower())

        row = self.session.execute(stmt).one()
        total_lookups = row[0] or 0
        cache_hits = row[1] or 0
        cache_misses = row[2] or 0
        incremental_analyses = row[3] or 0
        ai_requests_avoided = row[4] or 0
        estimated_tokens_saved = row[5] or 0

        hit_rate = (cache_hits / total_lookups * 100.0) if total_lookups > 0 else 0.0

        return {
            "total_lookups": total_lookups,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "incremental_analyses": incremental_analyses,
            "ai_requests_avoided": ai_requests_avoided,
            "estimated_tokens_saved": estimated_tokens_saved,
            "cache_hit_rate": hit_rate,
        }

    def query_events(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CacheEventRecord]:
        stmt = select(CacheEventRecord)
        if user_id:
            stmt = stmt.where(or_(CacheEventRecord.user_id == user_id, CacheEventRecord.user_id.is_(None)))
        if project_id:
            stmt = stmt.where(CacheEventRecord.project_id == project_id)
        if since:
            stmt = stmt.where(CacheEventRecord.created_at >= since)
        if until:
            stmt = stmt.where(CacheEventRecord.created_at <= until)
        if operation:
            stmt = stmt.where(func.lower(CacheEventRecord.operation) == operation.lower())

        stmt = stmt.order_by(desc(CacheEventRecord.created_at)).offset(offset).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def get_savings_breakdown(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Group savings by cache_type with hits, misses, requests avoided, and tokens avoided."""
        stmt = select(
            CacheEventRecord.cache_type,
            func.count(CacheEventRecord.id).label("total_lookups"),
            func.sum(case((CacheEventRecord.cache_hit.is_(True), 1), else_=0)).label("hits"),
            func.sum(case((CacheEventRecord.cache_hit.is_(False), 1), else_=0)).label("misses"),
            func.sum(case((CacheEventRecord.cache_hit.is_(True), CacheEventRecord.ai_requests_avoided), else_=0)).label("requests_avoided"),
            func.sum(case((CacheEventRecord.cache_hit.is_(True), CacheEventRecord.estimated_tokens_avoided), else_=0)).label("tokens_avoided"),
        ).group_by(CacheEventRecord.cache_type)

        if user_id:
            stmt = stmt.where(or_(CacheEventRecord.user_id == user_id, CacheEventRecord.user_id.is_(None)))
        if project_id:
            stmt = stmt.where(CacheEventRecord.project_id == project_id)
        if since:
            stmt = stmt.where(CacheEventRecord.created_at >= since)
        if until:
            stmt = stmt.where(CacheEventRecord.created_at <= until)
        if operation:
            stmt = stmt.where(func.lower(CacheEventRecord.operation) == operation.lower())

        rows = self.session.execute(stmt).all()
        return [
            {
                "cache_type": r[0],
                "total_lookups": r[1] or 0,
                "hits": r[2] or 0,
                "misses": r[3] or 0,
                "requests_avoided": r[4] or 0,
                "tokens_avoided": r[5] or 0,
            }
            for r in rows
        ]


class AnalysisCacheRepository:
    """Repository for exact and incremental analysis cache records."""

    def __init__(self, session: Session):
        self.session = session

    def get_exact(
        self,
        content_hash: str,
        operation: str,
        language: str = "python",
        objective: str = "balanced",
        symbol_name: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[AnalysisCacheRecord]:
        stmt = select(AnalysisCacheRecord).where(
            AnalysisCacheRecord.content_hash == content_hash,
            func.lower(AnalysisCacheRecord.operation) == operation.lower(),
            func.lower(AnalysisCacheRecord.language) == language.lower(),
            func.lower(AnalysisCacheRecord.objective) == objective.lower(),
        )
        if symbol_name:
            stmt = stmt.where(AnalysisCacheRecord.symbol_name == symbol_name)
        else:
            stmt = stmt.where(AnalysisCacheRecord.symbol_name.is_(None))

        if user_id:
            stmt = stmt.where(
                or_(
                    AnalysisCacheRecord.user_id == user_id,
                    AnalysisCacheRecord.user_id.is_(None),
                )
            )

        return self.session.execute(stmt).scalar_one_or_none()

    def store(
        self,
        content_hash: str,
        operation: str,
        result_json: dict,
        language: str = "python",
        objective: str = "balanced",
        symbol_name: Optional[str] = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        metadata_json: Optional[dict] = None,
    ) -> AnalysisCacheRecord:
        existing = self.get_exact(
            content_hash=content_hash,
            operation=operation,
            language=language,
            objective=objective,
            symbol_name=symbol_name,
            user_id=user_id,
        )
        if existing:
            existing.result_json = result_json
            if input_tokens is not None:
                existing.input_tokens = input_tokens
            if output_tokens is not None:
                existing.output_tokens = output_tokens
            if total_tokens is not None:
                existing.total_tokens = total_tokens
            if metadata_json:
                existing.metadata_json = metadata_json
            self.session.flush()
            return existing

        record = AnalysisCacheRecord(
            id=generate_id(),
            user_id=user_id,
            project_id=project_id,
            content_hash=content_hash,
            operation=operation,
            language=language,
            objective=objective,
            symbol_name=symbol_name,
            result_json=result_json,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            metadata_json=metadata_json,
        )
        self.session.add(record)
        self.session.flush()
        return record


class CertificateRepository:
    """Repository for optimization certificates."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> OptimizationCertificateRecord:
        cert = OptimizationCertificateRecord(id=kwargs.pop("id", generate_id()), **kwargs)
        self.session.add(cert)
        self.session.flush()
        return cert

    def get_for_experiment(
        self,
        experiment_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[OptimizationCertificateRecord]:
        stmt = select(OptimizationCertificateRecord).where(
            OptimizationCertificateRecord.experiment_id == experiment_id
        )
        if user_id:
            stmt = stmt.where(
                or_(
                    OptimizationCertificateRecord.user_id == user_id,
                    OptimizationCertificateRecord.user_id.is_(None),
                )
            )
        return self.session.execute(stmt).scalar_one_or_none()


class AuditRepository:
    """Repository for audit events."""

    def __init__(self, session: Session):
        self.session = session

    def log_event(
        self,
        event_type: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        details: Optional[dict] = None,
        correlation_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=generate_id(),
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            correlation_id=correlation_id,
        )
        self.session.add(event)
        self.session.flush()
        return event
