"""
Mutations API endpoints for MUTAGEN with user isolation.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mutagen.analysis.python_analyzer import PythonAnalyzer
from mutagen.api.deps import get_current_user
from mutagen.db.repositories import CandidateRepository, ExperimentRepository
from mutagen.db.session import get_session
from mutagen.services import ExperimentService

router = APIRouter(prefix="/mutations", tags=["mutations"])


@router.get("/{mutation_id}")
def get_mutation(mutation_id: str, current_user: dict = Depends(get_current_user)):
    """Get details for a specific mutation candidate."""
    svc = ExperimentService()
    cand = svc.get_candidate(mutation_id, user_id=current_user["id"])
    if not cand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mutation candidate not found")
    return cand


@router.get("/{mutation_id}/diff")
def get_mutation_diff(
    mutation_id: str,
    context: int = Query(3, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """Get source diff for a specific mutation candidate."""
    svc = ExperimentService()
    diff = svc.get_candidate_diff(mutation_id, user_id=current_user["id"], context=context)
    if not diff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mutation candidate diff not found")
    return diff


@router.post("/{mutation_id}/validate")
def validate_mutation(mutation_id: str, current_user: dict = Depends(get_current_user)):
    """Perform syntax and semantic validation for a mutation candidate."""
    with get_session() as session:
        cand_repo = CandidateRepository(session)
        exp_repo = ExperimentRepository(session)

        cand = cand_repo.get(mutation_id)
        if not cand:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mutation candidate not found")

        exp = exp_repo.get(cand.experiment_id, user_id=current_user["id"])
        if not exp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mutation candidate not found")

        analyzer = PythonAnalyzer()
        analysis = analyzer.analyze(cand.source_code, "candidate.py")

        cand_repo.update_status(
            mutation_id,
            "valid" if analysis.syntax_valid else "rejected",
            validation_passed=analysis.syntax_valid,
            validation_errors={"errors": analysis.syntax_errors} if not analysis.syntax_valid else None,
        )

        return {
            "candidate_id": mutation_id,
            "syntax_valid": analysis.syntax_valid,
            "syntax_errors": analysis.syntax_errors,
            "complexity_score": analysis.complexity_score,
        }
