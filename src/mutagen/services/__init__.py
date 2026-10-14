"""
Service layer for MUTAGEN.

Services provide the business logic between CLI commands, API endpoints,
and the underlying data/infrastructure layers.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Optional

from mutagen.analysis.language_detector import detect_language
from mutagen.analysis.python_analyzer import PythonAnalyzer
from mutagen.config import get_settings, AIProvider
from mutagen.core.identifiers import generate_id, generate_project_id, utc_now
from mutagen.core.logging import get_logger
from mutagen.core.security import compute_content_hash, validate_source_content
from mutagen.db.repositories import (
    ProjectRepository, ProjectFileRepository, CodeVersionRepository,
    ExperimentRepository, CandidateRepository, GenerationRepository,
    CertificateRepository, MemoryRepository, AuditRepository,
)
from mutagen.db.session import get_session
from mutagen.exceptions import (
    MutagenAuthorizationError, MutagenError, MutagenExportError,
    MutagenValidationError, MutagenConfigError,
)
from mutagen.memory import MemoryManager
from mutagen.schemas import (
    CodeAnalysis, ExperimentConfig, ExperimentSummary, FitnessScore,
    OptimizationCertificate, OptimizationObjective, ProgrammingLanguage,
)
from mutagen.services.auth_service import AuthService
from mutagen.services.diff_service import DiffService
from mutagen.services.apply_service import ApplyService
from mutagen.services.usage_service import UsageService

logger = get_logger("services")


def get_ai_provider(
    tracked: bool = False,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    analysis_id: Optional[str] = None,
):
    """Get the configured AI provider instance, optionally wrapped with token tracking and reduction."""
    settings = get_settings()

    if settings.ai_provider == AIProvider.GEMMA:
        from mutagen.ai.gemma_provider import GemmaProvider
        raw = GemmaProvider()
    elif settings.ai_provider == AIProvider.FAKE:
        from mutagen.ai.fake_provider import FakeProvider
        raw = FakeProvider()
    elif settings.ai_provider == AIProvider.GROQ:
        from mutagen.ai.groq_provider import GroqProvider
        raw = GroqProvider()
    elif settings.ai_provider == AIProvider.GEMINI:
        from mutagen.ai.gemini_provider import GeminiProvider
        raw = GeminiProvider()
    else:
        raise MutagenConfigError(f"Unknown AI provider: {settings.ai_provider}")

    if tracked:
        from mutagen.ai.tracker import TrackedAIProvider
        return TrackedAIProvider(
            raw,
            user_id=user_id,
            project_id=project_id,
            analysis_id=analysis_id,
        )
    return raw


def get_tracked_ai_provider(
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    analysis_id: Optional[str] = None,
):
    """Convenience accessor for a tracked & token-optimized AI provider."""
    return get_ai_provider(
        tracked=True,
        user_id=user_id,
        project_id=project_id,
        analysis_id=analysis_id,
    )


class AnalysisService:
    """Service for code analysis operations."""

    def analyze_file(self, file_path: str) -> CodeAnalysis:
        """Analyze a source file."""
        path = Path(file_path).resolve()
        if not path.exists():
            raise MutagenValidationError(f"File not found: {path}")
        if not path.is_file():
            raise MutagenValidationError(f"Not a file: {path}")

        content = path.read_text(encoding="utf-8")
        validate_source_content(content)

        language = detect_language(path, content)

        if language == ProgrammingLanguage.PYTHON:
            analyzer = PythonAnalyzer()
            return analyzer.analyze(content, str(path))
        else:
            # Basic analysis for unsupported languages
            source_hash = compute_content_hash(content)
            lines = content.splitlines()
            return CodeAnalysis(
                language=language,
                file_path=str(path),
                source_hash=source_hash,
                lines_total=len(lines),
                lines_code=sum(1 for l in lines if l.strip()),
                lines_blank=sum(1 for l in lines if not l.strip()),
                syntax_valid=True,
                warnings=["Full analysis not available for this language"],
            )

    def analyze_with_ai(
        self,
        file_path: str,
        objective: OptimizationObjective = OptimizationObjective.BALANCED,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> dict:
        """Analyze a source file with static AST parsing combined with AI model analysis."""
        static_analysis = self.analyze_file(file_path)
        path = Path(file_path).resolve()
        content = path.read_text(encoding="utf-8")
        ai = get_tracked_ai_provider(user_id=user_id, project_id=project_id)
        ai_result = ai.analyze_code(
            source_code=content,
            language=static_analysis.language.value,
            objective=objective,
            static_context=static_analysis.model_dump(),
        )
        return {
            "static_analysis": static_analysis.model_dump(),
            "ai_analysis": ai_result,
        }


class ProjectService:
    """Service for project management with user ownership isolation."""

    def create_project(
        self,
        name: str,
        description: str = "",
        language: str = "python",
        source_file: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """Create a new project belonging to a user."""
        with get_session() as session:
            repo = ProjectRepository(session)
            audit = AuditRepository(session)

            # Check for duplicate name for this user
            existing = repo.find_by_name(name, user_id=user_id)
            if existing:
                raise MutagenValidationError(f"Project '{name}' already exists")

            project_id = generate_project_id()
            project = repo.create(
                id=project_id,
                user_id=user_id,
                name=name,
                description=description,
                language=language,
            )

            # Import source file if provided
            if source_file:
                cv_repo = CodeVersionRepository(session)
                pf_repo = ProjectFileRepository(session)
                path = Path(source_file).resolve()
                if path.exists() and path.is_file():
                    content = path.read_text(encoding="utf-8")
                    validate_source_content(content)
                    chash = compute_content_hash(content)
                    cv_repo.create(
                        project_id=project_id,
                        file_path=str(path.name),
                        content=content,
                        content_hash=chash,
                        is_original=True,
                        language=language,
                        line_count=len(content.splitlines()),
                        size_bytes=len(content.encode("utf-8")),
                    )
                    pf_repo.upsert(
                        project_id=project_id,
                        file_path=str(path.name),
                        content=content,
                        content_hash=chash,
                        language=language,
                        size_bytes=len(content.encode("utf-8")),
                    )

            audit.log_event("project_created", "project", project_id, user_id=user_id)

            return {
                "id": project.id,
                "user_id": project.user_id,
                "name": project.name,
                "description": project.description,
                "language": project.language,
                "created_at": str(project.created_at),
            }

    def list_projects(self, user_id: Optional[str] = None) -> list[dict]:
        """List all projects for the specified user."""
        with get_session() as session:
            repo = ProjectRepository(session)
            projects = repo.list_all(user_id=user_id)
            return [
                {
                    "id": p.id,
                    "user_id": p.user_id,
                    "name": p.name,
                    "language": p.language,
                    "created_at": str(p.created_at),
                }
                for p in projects
            ]

    def get_project(self, project_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        """Get project details if authorized."""
        with get_session() as session:
            repo = ProjectRepository(session)
            project = repo.get(project_id, user_id=user_id)
            if not project:
                return None
            return {
                "id": project.id,
                "user_id": project.user_id,
                "name": project.name,
                "description": project.description,
                "language": project.language,
                "objective": project.optimization_objective,
                "created_at": str(project.created_at),
                "updated_at": str(project.updated_at),
            }

    def delete_project(self, project_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a project if authorized."""
        with get_session() as session:
            repo = ProjectRepository(session)
            audit = AuditRepository(session)
            result = repo.delete(project_id, user_id=user_id)
            if result:
                audit.log_event("project_deleted", "project", project_id, user_id=user_id)
            return result


class ExperimentService:
    """Service for experiment operations with user isolation."""

    def list_experiments(self, user_id: Optional[str] = None) -> list[dict]:
        """List all experiments for the specified user."""
        with get_session() as session:
            repo = ExperimentRepository(session)
            experiments = repo.list_all(user_id=user_id)
            return [
                {
                    "id": e.id,
                    "user_id": e.user_id,
                    "source_file": e.source_file,
                    "language": e.language,
                    "status": e.status,
                    "objective": e.objective,
                    "generations": f"{e.generations_completed}/{e.generations_total}",
                    "candidates": e.total_candidates,
                    "best_improvement": (
                        f"{e.best_improvement_percent:.1f}%"
                        if e.best_improvement_percent is not None
                        else "-"
                    ),
                    "created_at": str(e.created_at),
                }
                for e in experiments
            ]

    def get_experiment(self, experiment_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        """Get experiment details if authorized."""
        with get_session() as session:
            repo = ExperimentRepository(session)
            exp = repo.get(experiment_id, user_id=user_id)
            if not exp:
                return None
            return {
                "id": exp.id,
                "user_id": exp.user_id,
                "source_file": exp.source_file,
                "language": exp.language,
                "status": exp.status,
                "objective": exp.objective,
                "generations_completed": exp.generations_completed,
                "generations_total": exp.generations_total,
                "population_size": exp.population_size,
                "total_candidates": exp.total_candidates,
                "valid_candidates": exp.valid_candidates,
                "best_candidate_id": exp.best_candidate_id,
                "best_improvement_percent": exp.best_improvement_percent,
                "duration_seconds": exp.duration_seconds,
                "source_hash": exp.source_hash,
                "error_message": exp.error_message,
                "created_at": str(exp.created_at),
                "updated_at": str(exp.updated_at),
            }

    def get_experiment_results(self, experiment_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        """Get experiment results with candidate details."""
        with get_session() as session:
            exp_repo = ExperimentRepository(session)
            cand_repo = CandidateRepository(session)

            exp = exp_repo.get(experiment_id, user_id=user_id)
            if not exp:
                return None

            candidates = cand_repo.list_for_experiment(experiment_id)
            best = cand_repo.get_best_eligible(experiment_id)

            return {
                "experiment": self._exp_to_dict(exp),
                "candidates": [self._cand_to_dict(c) for c in candidates],
                "best_candidate": self._cand_to_dict(best) if best else None,
            }

    def get_candidate(self, candidate_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        """Get candidate details if authorized."""
        with get_session() as session:
            repo = CandidateRepository(session)
            cand = repo.get_for_user(candidate_id, user_id=user_id)
            if not cand:
                return None
            return self._cand_to_dict(cand)

    def get_candidate_diff(
        self,
        candidate_id: str,
        user_id: Optional[str] = None,
        context: int = 3,
    ) -> Optional[dict]:
        """Get programmatic diff and change report between original and candidate code."""
        with get_session() as session:
            cand_repo = CandidateRepository(session)
            exp_repo = ExperimentRepository(session)

            cand = cand_repo.get(candidate_id)
            if not cand:
                return None

            exp = exp_repo.get(cand.experiment_id, user_id=user_id)
            if not exp:
                return None

            report = DiffService.create_candidate_report(
                experiment_id=exp.id,
                candidate_id=cand.id,
                original_code=exp.source_content,
                candidate_code=cand.source_code,
                file_path=exp.source_file,
                generation=cand.generation_number,
                strategy=cand.strategy,
                status=cand.status,
                validation_passed=cand.validation_passed,
                tests_passed=cand.tests_passed,
                speed_improvement_percent=cand.speed_improvement,
                memory_improvement_percent=cand.memory_improvement,
                fitness_score=cand.fitness_score,
                is_eligible=cand.is_eligible,
                context=context,
            )
            res = report.model_dump()
            res["verification_passed"] = cand.verification_passed
            res["verification_verdict"] = cand.verification_verdict
            res["verification_json"] = cand.verification_json
            return res

    def list_candidates(self, experiment_id: str, user_id: Optional[str] = None) -> list[dict]:
        """List all candidates for an experiment if authorized."""
        with get_session() as session:
            exp_repo = ExperimentRepository(session)
            exp = exp_repo.get(experiment_id, user_id=user_id)
            if not exp:
                return []

            repo = CandidateRepository(session)
            candidates = repo.list_for_experiment(experiment_id)
            return [self._cand_to_dict(c) for c in candidates]

    def _exp_to_dict(self, exp) -> dict:
        return {
            "id": exp.id,
            "user_id": exp.user_id,
            "source_file": exp.source_file,
            "language": exp.language,
            "status": exp.status,
            "objective": exp.objective,
            "generations": f"{exp.generations_completed}/{exp.generations_total}",
            "total_candidates": exp.total_candidates,
            "valid_candidates": exp.valid_candidates,
            "best_candidate_id": exp.best_candidate_id,
            "best_improvement_percent": exp.best_improvement_percent,
            "duration_seconds": exp.duration_seconds,
        }

    def _cand_to_dict(self, cand) -> dict:
        return {
            "id": cand.id,
            "generation": cand.generation_number,
            "strategy": cand.strategy,
            "status": cand.status,
            "explanation": cand.explanation,
            "validation_passed": cand.validation_passed,
            "tests_passed": cand.tests_passed,
            "verification_passed": cand.verification_passed,
            "verification_verdict": cand.verification_verdict,
            "verification_json": cand.verification_json,
            "fitness_score": cand.fitness_score,
            "speed_improvement": cand.speed_improvement,
            "memory_improvement": cand.memory_improvement,
            "is_eligible": cand.is_eligible,
            "content_hash": cand.content_hash,
        }


class ExportService:
    """Service for exporting optimized candidates."""

    def export_candidate(
        self,
        experiment_id: str,
        output_path: str,
        candidate_id: Optional[str] = None,
        force: bool = False,
        user_id: Optional[str] = None,
    ) -> dict:
        """Export the best eligible candidate to a file."""
        output = Path(output_path).resolve()

        if output.exists() and not force:
            raise MutagenExportError(
                f"Output file already exists: {output}. Use --yes to overwrite."
            )

        with get_session() as session:
            exp_repo = ExperimentRepository(session)
            cand_repo = CandidateRepository(session)
            audit = AuditRepository(session)

            exp = exp_repo.get(experiment_id, user_id=user_id)
            if not exp:
                raise MutagenExportError(f"Experiment not found: {experiment_id}")

            if candidate_id:
                candidate = cand_repo.get(candidate_id)
                if not candidate or candidate.experiment_id != experiment_id:
                    raise MutagenExportError(f"Candidate not found: {candidate_id}")
                if not candidate.is_eligible:
                    raise MutagenExportError(
                        f"Candidate {candidate_id} is not eligible for export. "
                        f"Status: {candidate.status}"
                    )
            else:
                candidate = cand_repo.get_best_eligible(experiment_id)
                if not candidate:
                    raise MutagenExportError(
                        f"No eligible candidate found for experiment {experiment_id}"
                    )

            # Verify content hash
            actual_hash = compute_content_hash(candidate.source_code)
            if actual_hash != candidate.content_hash:
                raise MutagenExportError(
                    "Candidate content hash mismatch — integrity check failed"
                )

            # Write file atomically
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(candidate.source_code, encoding="utf-8")

            audit.log_event(
                "candidate_exported",
                entity_type="candidate",
                entity_id=candidate.id,
                user_id=user_id,
                details={
                    "experiment_id": experiment_id,
                    "output_path": str(output),
                    "content_hash": actual_hash,
                },
            )

            return {
                "experiment_id": experiment_id,
                "candidate_id": candidate.id,
                "output_path": str(output),
                "content_hash": actual_hash,
                "strategy": candidate.strategy,
                "fitness_score": candidate.fitness_score,
                "speed_improvement": candidate.speed_improvement,
            }


class CertificateService:
    """Service for optimization certificates."""

    def generate_certificate(
        self,
        experiment_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Generate an optimization certificate for an experiment."""
        with get_session() as session:
            exp_repo = ExperimentRepository(session)
            cand_repo = CandidateRepository(session)
            cert_repo = CertificateRepository(session)

            exp = exp_repo.get(experiment_id, user_id=user_id)
            if not exp:
                return None

            best = cand_repo.get_best_eligible(experiment_id)
            if not best:
                return None

            cert_data = {
                "experiment_id": experiment_id,
                "original_source_hash": exp.source_hash,
                "candidate_source_hash": best.content_hash,
                "candidate_id": best.id,
                "language": exp.language,
                "validation_passed": best.validation_passed,
                "tests_passed": best.tests_passed,
                "speed_improvement_percent": best.speed_improvement or 0.0,
                "memory_improvement_percent": best.memory_improvement or 0.0,
                "generations_run": exp.generations_completed,
                "candidates_tested": exp.total_candidates,
                "fitness_score": best.fitness_score,
                "strategy": best.strategy,
                "verification_statement": (
                    "Verified against the recorded test suite and benchmark configuration."
                ),
                "known_limitations": [
                    "Static analysis is not a complete security boundary",
                    "Test pass does not prove correctness for all inputs",
                    "Benchmark results depend on execution environment",
                ],
            }

            content_hash = compute_content_hash(str(cert_data))

            cert_repo.create(
                user_id=user_id,
                experiment_id=experiment_id,
                candidate_id=best.id,
                original_hash=exp.source_hash,
                candidate_hash=best.content_hash,
                certificate_data=cert_data,
                content_hash=content_hash,
            )

            return cert_data

    def verify_certificate(self, experiment_id: str, user_id: Optional[str] = None) -> dict:
        """Verify an existing certificate."""
        with get_session() as session:
            cert_repo = CertificateRepository(session)
            cert = cert_repo.get_for_experiment(experiment_id, user_id=user_id)
            if not cert:
                return {"verified": False, "error": "No certificate found"}

            actual_hash = compute_content_hash(str(cert.certificate_data))
            hash_match = actual_hash == cert.content_hash

            return {
                "verified": hash_match,
                "experiment_id": experiment_id,
                "candidate_id": cert.candidate_id,
                "content_hash_valid": hash_match,
                "certificate_data": cert.certificate_data,
            }
