"""
Tests for MUTAGEN User Isolation & Authorization.

Covers:
- User A cannot read User B's project
- User A cannot delete User B's project
- User A cannot access User B's experiments
- User A cannot inspect User B's mutations
- User A cannot retrieve User B's memory
- User A cannot apply User B's candidate
"""

import pytest
from mutagen.services.auth_service import AuthService
from mutagen.services import ProjectService, ExperimentService, ApplyService
from mutagen.db.session import get_db_context
from mutagen.db.repositories import (
    ExperimentRepository, CandidateRepository, MemoryRepository
)
from mutagen.exceptions import MutagenAuthorizationError
from mutagen.schemas import CandidateStatus, ExperimentStatus


@pytest.fixture
def users_a_and_b():
    auth_svc = AuthService()
    user_a = auth_svc.register(
        username="user_a",
        email="user_a@example.com",
        password="PasswordA123!",
    )
    user_b = auth_svc.register(
        username="user_b",
        email="user_b@example.com",
        password="PasswordB123!",
    )
    return user_a, user_b


def test_user_a_cannot_read_or_delete_user_b_project(users_a_and_b):
    user_a, user_b = users_a_and_b
    proj_svc = ProjectService()

    # User B creates a project
    proj_b = proj_svc.create_project(
        name="Project-B",
        description="Private to User B",
        language="python",
        user_id=user_b["id"],
    )

    # User A listing projects should not see User B's project
    projects_a = proj_svc.list_projects(user_id=user_a["id"])
    assert not any(p["id"] == proj_b["id"] for p in projects_a)

    # User A fetching User B's project by ID returns None (not found / inaccessible)
    assert proj_svc.get_project(proj_b["id"], user_id=user_a["id"]) is None

    # User A attempting to delete User B's project returns False
    assert proj_svc.delete_project(proj_b["id"], user_id=user_a["id"]) is False

    # But User B CAN retrieve their project
    assert proj_svc.get_project(proj_b["id"], user_id=user_b["id"]) is not None


def test_user_a_cannot_access_user_b_experiment(users_a_and_b):
    user_a, user_b = users_a_and_b
    exp_svc = ExperimentService()

    # Direct DB creation of User B's experiment
    with get_db_context() as session:
        exp_repo = ExperimentRepository(session)
        exp_b = exp_repo.create(
            id="exp_b_private",
            user_id=user_b["id"],
            source_file="sorter.py",
            source_hash="hash_b",
            source_content="def sort(): pass",
            language="python",
            status=ExperimentStatus.SUCCEEDED.value,
        )
        session.commit()

    # User A listing experiments should not see exp_b
    user_a_experiments = exp_svc.list_experiments(user_id=user_a["id"])
    assert not any(e["id"] == "exp_b_private" for e in user_a_experiments)

    # User A getting experiment details returns None
    assert exp_svc.get_experiment("exp_b_private", user_id=user_a["id"]) is None

    # User B CAN access their own experiment
    assert exp_svc.get_experiment("exp_b_private", user_id=user_b["id"]) is not None


def test_user_a_cannot_inspect_user_b_mutations(users_a_and_b):
    user_a, user_b = users_a_and_b
    exp_svc = ExperimentService()

    # Direct DB creation of User B experiment & candidate
    with get_db_context() as session:
        exp_repo = ExperimentRepository(session)
        cand_repo = CandidateRepository(session)
        exp_repo.create(
            id="exp_b_candidates",
            user_id=user_b["id"],
            source_file="sorter.py",
            source_hash="hash_b",
            source_content="def sort(): pass",
            language="python",
        )
        cand_repo.create(
            id="cand_b_secret",
            experiment_id="exp_b_candidates",
            generation_number=1,
            source_code="def sort(): return []",
            content_hash="hash_cand_b",
            strategy="vectorize",
            status=CandidateStatus.BEST_ELIGIBLE.value,
        )
        session.commit()

    # User A cannot get candidate directly
    assert exp_svc.get_candidate("cand_b_secret", user_id=user_a["id"]) is None

    # User B CAN access candidate
    assert exp_svc.get_candidate("cand_b_secret", user_id=user_b["id"]) is not None


def test_user_a_cannot_retrieve_user_b_memory(users_a_and_b):
    user_a, user_b = users_a_and_b

    with get_db_context() as session:
        mem_repo = MemoryRepository(session)
        mem_repo.create(
            id="mem_b_1",
            user_id=user_b["id"],
            memory_type="pattern",
            content="Private pattern for User B",
            language="python",
        )
        session.commit()

        # Querying memory for User A should not return User B's memory
        records_a = mem_repo.search(user_id=user_a["id"])
        assert not any(r.id == "mem_b_1" for r in records_a)

        # Querying memory for User B returns User B's memory
        records_b = mem_repo.search(user_id=user_b["id"])
        assert any(r.id == "mem_b_1" for r in records_b)


def test_user_a_cannot_apply_user_b_candidate(users_a_and_b, tmp_path):
    user_a, user_b = users_a_and_b
    apply_svc = ApplyService()

    target_file = tmp_path / "app.py"
    target_file.write_text("def run(): pass\n", encoding="utf-8")

    with get_db_context() as session:
        exp_repo = ExperimentRepository(session)
        cand_repo = CandidateRepository(session)
        exp_repo.create(
            id="exp_b_apply",
            user_id=user_b["id"],
            source_file=str(target_file),
            source_hash="original_hash",
            source_content="def run(): pass\n",
            language="python",
        )
        cand_repo.create(
            id="cand_b_apply",
            experiment_id="exp_b_apply",
            generation_number=1,
            source_code="def run(): return 42\n",
            content_hash="candidate_hash",
            strategy="constant_fold",
            status=CandidateStatus.BEST_ELIGIBLE.value,
        )
        session.commit()

    # User A attempts to apply candidate -> must raise MutagenAuthorizationError
    with pytest.raises(MutagenAuthorizationError):
        apply_svc.apply_candidate(
            experiment_id="exp_b_apply",
            candidate_id="cand_b_apply",
            user_id=user_a["id"],
        )
