"""
Projects API endpoints for MUTAGEN with user-level isolation.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from mutagen.api.deps import get_current_user
from mutagen.exceptions import MutagenValidationError
from mutagen.schemas import ExperimentConfig
from mutagen.services import ProjectService, ExperimentService, get_ai_provider
from mutagen.evolution.engine import EvolutionEngine

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""
    language: str = "python"
    source_file: Optional[str] = None


class ProjectExperimentRequest(BaseModel):
    source_file: str
    generations: int = 3
    population_size: int = 2
    objective: str = "balanced"


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(req: ProjectCreateRequest, current_user: dict = Depends(get_current_user)):
    """Create a new project isolated to the authenticated user."""
    svc = ProjectService()
    try:
        project = svc.create_project(
            name=req.name,
            description=req.description,
            language=req.language,
            source_file=req.source_file,
            user_id=current_user["id"],
        )
        return project
    except MutagenValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("")
def list_projects(current_user: dict = Depends(get_current_user)):
    """List projects belonging only to the authenticated user."""
    svc = ProjectService()
    return svc.list_projects(user_id=current_user["id"])


@router.get("/{project_id}")
def get_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """Get project details if owned by authenticated user."""
    svc = ProjectService()
    project = svc.get_project(project_id, user_id=current_user["id"])
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.delete("/{project_id}")
def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a project owned by authenticated user."""
    svc = ProjectService()
    success = svc.delete_project(project_id, user_id=current_user["id"])
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"message": "Project deleted successfully"}


@router.post("/{project_id}/experiments", status_code=status.HTTP_202_ACCEPTED)
def start_project_experiment(
    project_id: str,
    req: ProjectExperimentRequest,
    current_user: dict = Depends(get_current_user),
):
    """Launch an evolutionary experiment associated with a user's project."""
    proj_svc = ProjectService()
    project = proj_svc.get_project(project_id, user_id=current_user["id"])
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    config = ExperimentConfig(
        source_file=req.source_file,
        user_id=current_user["id"],
        project_id=project_id,
        generations=req.generations,
        population_size=req.population_size,
    )
    ai_provider = get_ai_provider()
    engine = EvolutionEngine(ai_provider=ai_provider, config=config)
    summary = engine.run()
    return summary.model_dump()
