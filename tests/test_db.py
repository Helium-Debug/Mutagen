"""
Tests for database models and repositories.
"""

import pytest
from mutagen.db.repositories import (
    ProjectRepository, CodeVersionRepository, ExperimentRepository,
    CandidateRepository, GenerationRepository, MemoryRepository,
)
from mutagen.schemas import CandidateStatus, ExperimentStatus


def test_project_and_code_version_lifecycle(db_session):
    proj_repo = ProjectRepository(db_session)
    code_repo = CodeVersionRepository(db_session)

    project = proj_repo.create(
        id="proj_alpha",
        name="Alpha Optimizer",
        description="Test project",
        language="python",
    )
    db_session.commit()

    assert project.id == "proj_alpha"
    assert project.name == "Alpha Optimizer"

    # Add code version
    code_ver = code_repo.create(
        id="ver_1",
        project_id="proj_alpha",
        file_path="src/main.py",
        content="print('alpha')",
        content_hash="hash_alpha_1",
        is_original=True,
    )
    db_session.commit()

    versions = code_repo.list_for_project("proj_alpha")
    assert len(versions) == 1
    assert versions[0].content == "print('alpha')"

    # Cascade delete
    proj_repo.delete("proj_alpha")
    db_session.commit()

    assert proj_repo.get("proj_alpha") is None
    assert len(code_repo.list_for_project("proj_alpha")) == 0


def test_experiment_and_candidate_lifecycle(db_session):
    exp_repo = ExperimentRepository(db_session)
    cand_repo = CandidateRepository(db_session)

    exp = exp_repo.create(
        id="exp_test",
        source_file="math.py",
        source_hash="sha256_hash",
        source_content="def add(a, b): return a + b",
        language="python",
        objective="speed",
        status=ExperimentStatus.RUNNING.value,
    )
    db_session.commit()

    cand = cand_repo.create(
        id="cand_1",
        experiment_id="exp_test",
        generation_number=1,
        source_code="def add(a, b): return a + b",
        content_hash="sha256_cand",
        strategy="general",
        status=CandidateStatus.VALID.value,
    )
    db_session.commit()

    cand_repo.update_status(
        "cand_1",
        CandidateStatus.BEST_ELIGIBLE.value,
        fitness_score=0.95,
        speed_improvement=45.5,
    )
    db_session.commit()

    retrieved = cand_repo.get("cand_1")
    assert retrieved.status == CandidateStatus.BEST_ELIGIBLE.value
    assert retrieved.fitness_score == 0.95
    assert retrieved.speed_improvement == 45.5
