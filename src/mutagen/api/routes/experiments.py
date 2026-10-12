"""
Experiments API endpoints for MUTAGEN with user isolation.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mutagen.api.deps import get_current_user
from mutagen.db.session import get_session
from mutagen.db.repositories import ExperimentRepository, CandidateRepository
from mutagen.services import ExperimentService, DiffService

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("")
def list_experiments(current_user: dict = Depends(get_current_user)):
    """List experiments owned by the current user."""
    svc = ExperimentService()
    return svc.list_experiments(user_id=current_user["id"])


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str, current_user: dict = Depends(get_current_user)):
    """Get experiment details for current user."""
    svc = ExperimentService()
    exp = svc.get_experiment(experiment_id, user_id=current_user["id"])
    if not exp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    return exp


@router.get("/{experiment_id}/mutations")
def list_mutations(experiment_id: str, current_user: dict = Depends(get_current_user)):
    """List all mutation candidates for an experiment."""
    svc = ExperimentService()
    exp = svc.get_experiment(experiment_id, user_id=current_user["id"])
    if not exp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    return svc.list_candidates(experiment_id, user_id=current_user["id"])


@router.get("/{experiment_id}/diff")
def get_experiment_diff(
    experiment_id: str,
    candidate_id: Optional[str] = Query(None),
    context: int = Query(3, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """Get programmatic diff between original and candidate code."""
    svc = ExperimentService()
    exp = svc.get_experiment(experiment_id, user_id=current_user["id"])
    if not exp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")

    cid = candidate_id or exp.get("best_candidate_id")
    if not cid:
        with get_session() as session:
            c_repo = CandidateRepository(session)
            best_c = c_repo.get_best_eligible(experiment_id)
            if best_c:
                cid = best_c.id
            else:
                all_c = c_repo.list_for_experiment(experiment_id)
                if all_c:
                    cid = all_c[0].id

    if not cid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No eligible candidate diff available")

    diff_report = svc.get_candidate_diff(cid, user_id=current_user["id"], context=context)
    if not diff_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return diff_report


@router.get("/{experiment_id}/results")
def get_experiment_results(experiment_id: str, current_user: dict = Depends(get_current_user)):
    """Get comprehensive experiment results with candidate metrics."""
    svc = ExperimentService()
    results = svc.get_experiment_results(experiment_id, user_id=current_user["id"])
    if not results:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    return results


@router.post("/{experiment_id}/cancel")
def cancel_experiment(experiment_id: str, current_user: dict = Depends(get_current_user)):
    """Cancel a running experiment."""
    with get_session() as session:
        repo = ExperimentRepository(session)
        exp = repo.get(experiment_id, user_id=current_user["id"])
        if not exp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
        repo.update_status(experiment_id, "cancelled")
        return {"message": "Experiment cancelled successfully"}
