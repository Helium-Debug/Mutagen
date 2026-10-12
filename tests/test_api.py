"""
Tests for FastAPI REST API endpoints.

Covers:
- /health public health check
- /api/v1/auth/* (register, login, refresh, logout, me)
- Unauthenticated rejection on protected endpoints (401)
- /api/v1/projects CRUD with user isolation
- /api/v1/experiments lifecycle & endpoints
- /api/v1/mutations endpoints & diffs
"""

import pytest
from fastapi.testclient import TestClient

from mutagen.api.app import app
from mutagen.db.session import get_db_context
from mutagen.db.repositories import ExperimentRepository, CandidateRepository
from mutagen.schemas import CandidateStatus, ExperimentStatus

client = TestClient(app)


def test_public_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")


def test_api_unauthenticated_protected_endpoints():
    # Protected endpoints without token must return 401 or 403
    res_me = client.get("/api/v1/auth/me")
    assert res_me.status_code in (401, 403)

    res_proj = client.get("/api/v1/projects")
    assert res_proj.status_code in (401, 403)

    res_create_proj = client.post("/api/v1/projects", json={"name": "P1"})
    assert res_create_proj.status_code in (401, 403)


def test_api_auth_lifecycle():
    # 1. Register
    reg_payload = {
        "username": "api_user",
        "email": "api_user@example.com",
        "password": "Password123!",
    }
    res_reg = client.post("/api/v1/auth/register", json=reg_payload)
    assert res_reg.status_code == 201
    user_data = res_reg.json()
    assert user_data["username"] == "api_user"

    # 2. Duplicate registration rejection
    res_dup = client.post("/api/v1/auth/register", json=reg_payload)
    assert res_dup.status_code == 400

    # 3. Login
    login_payload = {
        "username_or_email": "api_user",
        "password": "Password123!",
    }
    res_login = client.post("/api/v1/auth/login", json=login_payload)
    assert res_login.status_code == 200
    tokens = res_login.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    headers = {"Authorization": f"Bearer {access_token}"}

    # 4. Get Current User (GET /auth/me)
    res_me = client.get("/api/v1/auth/me", headers=headers)
    assert res_me.status_code == 200
    assert res_me.json()["username"] == "api_user"

    # 5. Refresh token
    res_ref = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert res_ref.status_code == 200
    new_tokens = res_ref.json()
    assert "access_token" in new_tokens
    new_access_token = new_tokens["access_token"]
    new_refresh_token = new_tokens["refresh_token"]

    # 6. Logout
    res_logout = client.post("/api/v1/auth/logout", json={"refresh_token": new_refresh_token})
    assert res_logout.status_code == 200


def test_api_projects_crud_and_isolation():
    # Register two users
    client.post("/api/v1/auth/register", json={
        "username": "alice_api", "email": "alice_api@example.com", "password": "Password123!"
    })
    client.post("/api/v1/auth/register", json={
        "username": "bob_api", "email": "bob_api@example.com", "password": "Password123!"
    })

    # Log in Alice
    res_a = client.post("/api/v1/auth/login", json={"username_or_email": "alice_api", "password": "Password123!"})
    assert res_a.status_code == 200
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Log in Bob
    res_b = client.post("/api/v1/auth/login", json={"username_or_email": "bob_api", "password": "Password123!"})
    assert res_b.status_code == 200
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Alice creates a project
    res_p = client.post("/api/v1/projects", json={
        "name": "AliceProject",
        "description": "Confidential",
        "language": "python"
    }, headers=headers_a)
    assert res_p.status_code == 201
    proj_a_id = res_p.json()["id"]

    # Alice can list her project
    list_a = client.get("/api/v1/projects", headers=headers_a).json()
    assert any(p["id"] == proj_a_id for p in list_a)

    # Bob lists projects -> Alice's project must NOT appear
    list_b = client.get("/api/v1/projects", headers=headers_b).json()
    assert not any(p["id"] == proj_a_id for p in list_b)

    # Bob requests Alice's project -> must be 404 or 403
    get_b = client.get(f"/api/v1/projects/{proj_a_id}", headers=headers_b)
    assert get_b.status_code in (403, 404)


def test_api_experiments_and_mutations():
    # Register user
    client.post("/api/v1/auth/register", json={
        "username": "exp_user", "email": "exp_user@example.com", "password": "Password123!"
    })
    res_login = client.post("/api/v1/auth/login", json={"username_or_email": "exp_user", "password": "Password123!"})
    assert res_login.status_code == 200
    token = res_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    user_info = client.get("/api/v1/auth/me", headers=headers).json()
    user_id = user_info["id"]

    # Prepopulate DB with experiment & candidate
    with get_db_context() as session:
        exp_repo = ExperimentRepository(session)
        cand_repo = CandidateRepository(session)
        exp = exp_repo.create(
            id="exp_api_test",
            user_id=user_id,
            source_file="math.py",
            source_hash="hash123",
            source_content="def add(a, b): return a + b\n",
            language="python",
            status=ExperimentStatus.SUCCEEDED.value,
            best_candidate_id="cand_api_test",
        )
        cand = cand_repo.create(
            id="cand_api_test",
            experiment_id="exp_api_test",
            generation_number=1,
            source_code="def add(a, b):\n    return a + b\n",
            content_hash="hash456",
            status=CandidateStatus.BEST_ELIGIBLE.value,
        )
        session.commit()

    # GET /api/v1/experiments/{id}
    res_exp = client.get("/api/v1/experiments/exp_api_test", headers=headers)
    assert res_exp.status_code == 200
    assert res_exp.json()["id"] == "exp_api_test"

    # GET /api/v1/experiments/{id}/mutations
    res_muts = client.get("/api/v1/experiments/exp_api_test/mutations", headers=headers)
    assert res_muts.status_code == 200
    assert len(res_muts.json()) >= 1

    # GET /api/v1/experiments/{id}/diff
    res_diff = client.get("/api/v1/experiments/exp_api_test/diff", headers=headers)
    assert res_diff.status_code == 200

    # GET /api/v1/mutations/{id}
    res_cand = client.get("/api/v1/mutations/cand_api_test", headers=headers)
    assert res_cand.status_code == 200
    assert res_cand.json()["id"] == "cand_api_test"

    # GET /api/v1/mutations/{id}/diff
    res_cdiff = client.get("/api/v1/mutations/cand_api_test/diff", headers=headers)
    assert res_cdiff.status_code == 200

    # POST /api/v1/mutations/{id}/validate
    res_val = client.post("/api/v1/mutations/cand_api_test/validate", headers=headers)
    assert res_val.status_code == 200
    assert res_val.json()["syntax_valid"] is True

    # GET /api/v1/experiments/{id}/results
    res_res = client.get("/api/v1/experiments/exp_api_test/results", headers=headers)
    assert res_res.status_code == 200
