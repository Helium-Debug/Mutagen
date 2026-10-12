"""
Application service for safely applying optimized code candidates.

Verifies candidate integrity, detects disk conflicts, creates automated backups,
and safely replaces target source files or runs in dry-run mode.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from mutagen.core.security import compute_content_hash, validate_path_safety
from mutagen.db.repositories import (
    AuditRepository, CandidateRepository, ExperimentRepository, ProjectRepository,
)
from mutagen.db.session import get_session
from mutagen.exceptions import (
    MutagenAuthorizationError, MutagenExportError, MutagenValidationError,
)
from mutagen.services.diff_service import DiffService


class ApplyService:
    """Service for safely applying optimized code candidates to disk."""

    def plan_apply(
        self,
        experiment_id: str,
        candidate_id: Optional[str] = None,
        target_file: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Prepare an application plan without touching the target file.
        Detects conflicts and computes diffs.
        """
        with get_session() as session:
            exp_repo = ExperimentRepository(session)
            cand_repo = CandidateRepository(session)

            exp = exp_repo.get(experiment_id)
            if not exp:
                raise MutagenValidationError(f"Experiment not found: {experiment_id}")

            if user_id and exp.user_id and exp.user_id != user_id:
                raise MutagenAuthorizationError("You do not have permission to access this experiment.")

            if candidate_id:
                candidate = cand_repo.get(candidate_id)
                if not candidate:
                    raise MutagenValidationError(f"Candidate not found: {candidate_id}")
                if candidate.experiment_id != experiment_id:
                    raise MutagenValidationError("Candidate does not belong to the specified experiment.")
            else:
                candidate = cand_repo.get_best_eligible(experiment_id)
                if not candidate:
                    raise MutagenValidationError(
                        f"No eligible candidate found for experiment {experiment_id}"
                    )

            # Integrity check
            actual_hash = compute_content_hash(candidate.source_code)
            if actual_hash != candidate.content_hash:
                raise MutagenValidationError(
                    "Candidate integrity verification failed: hash mismatch."
                )

            # Determine file path to update
            file_to_apply = Path(target_file or exp.source_file).resolve()
            has_conflict = False
            current_on_disk_hash = None

            if file_to_apply.exists():
                current_content = file_to_apply.read_text(encoding="utf-8")
                current_on_disk_hash = compute_content_hash(current_content)
                if current_on_disk_hash != exp.source_hash:
                    has_conflict = True

            diff_text = DiffService.compute_unified_diff(
                original=exp.source_content,
                candidate=candidate.source_code,
                fromfile=f"a/{file_to_apply.name} (original)",
                tofile=f"b/{file_to_apply.name} (optimized)",
            )
            summary = DiffService.summarize_changes(
                original=exp.source_content,
                candidate=candidate.source_code,
                file_path=str(file_to_apply),
            )

            return {
                "experiment_id": experiment_id,
                "candidate_id": candidate.id,
                "file_path": str(file_to_apply),
                "strategy": candidate.strategy,
                "speed_improvement": candidate.speed_improvement,
                "fitness_score": candidate.fitness_score,
                "candidate_source": candidate.source_code,
                "candidate_hash": candidate.content_hash,
                "original_hash": exp.source_hash,
                "current_on_disk_hash": current_on_disk_hash,
                "has_conflict": has_conflict,
                "diff_text": diff_text,
                "summary": summary.model_dump(),
            }

    def apply_candidate(
        self,
        experiment_id: str,
        candidate_id: Optional[str] = None,
        target_file: Optional[str] = None,
        dry_run: bool = False,
        backup: bool = True,
        force: bool = False,
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Apply the selected candidate to the target source file.
        """
        plan = self.plan_apply(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            target_file=target_file,
            user_id=user_id,
        )

        file_path = Path(plan["file_path"])

        if plan["has_conflict"] and not force:
            raise MutagenValidationError(
                f"Conflict detected: The file '{file_path.name}' has been modified on disk "
                f"since the experiment was created. Review changes or use --force to overwrite."
            )

        if dry_run:
            return {
                **plan,
                "dry_run": True,
                "applied": False,
                "backup_path": None,
                "message": "Dry-run completed. No files were modified.",
            }

        # Create backup if file exists
        backup_path = None
        if file_path.exists() and backup:
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, backup_path)

        # Write candidate source code atomically
        temp_file = file_path.with_suffix(file_path.suffix + ".tmp")
        temp_file.write_text(plan["candidate_source"], encoding="utf-8")
        temp_file.replace(file_path)

        with get_session() as session:
            audit = AuditRepository(session)
            audit.log_event(
                event_type="candidate_applied",
                entity_type="candidate",
                entity_id=plan["candidate_id"],
                user_id=user_id,
                details={
                    "experiment_id": experiment_id,
                    "target_file": str(file_path),
                    "backup_path": str(backup_path) if backup_path else None,
                    "candidate_hash": plan["candidate_hash"],
                },
            )

        return {
            **plan,
            "dry_run": False,
            "applied": True,
            "backup_path": str(backup_path) if backup_path else None,
            "message": f"Successfully applied candidate to {file_path}",
        }
