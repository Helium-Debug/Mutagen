"""
Database repository layer for MUTAGEN.

Provides CRUD operations and access control isolation for all persistent entities.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, desc, func, or_
from sqlalchemy.orm import Session

from mutagen.core.identifiers import generate_id, utc_now
from mutagen.models import (
    User, RefreshToken, Project, ProjectFile, CodeVersion, Experiment,
    ExperimentGeneration, MutationCandidate, SourceDiff, MemoryRecord,
    AIUsageRecord, OptimizationCertificateRecord, AuditEvent,
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
        candidate = MutationCandidate(id=kwargs.pop("id", generate_id()), **kwargs)
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
    """Repository for AI usage tracking."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> AIUsageRecord:
        record = AIUsageRecord(id=kwargs.pop("id", generate_id()), **kwargs)
        self.session.add(record)
        self.session.flush()
        return record

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
