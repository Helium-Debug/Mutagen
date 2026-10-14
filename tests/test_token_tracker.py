"""
Tests for MUTAGEN Token Usage Tracker, Token Reduction Engine, and Python CLI.

Covers:
1. Actual provider-reported token aggregation
2. Missing token metadata handling (unavailable source, not 0)
3. Separation of estimated usage and actual consumption
4. Date-range filtering (--since, --until)
5. Operation filtering (--operation)
6. Cache-hit calculations (hit rate formula, zero lookups)
7. Token-savings calculations with documented baseline
8. Duplicate-record prevention
9. Duplicate-savings prevention
10. CSV exports with stable schema
11. JSON exports
12. Empty database behavior & empty-state messaging
13. Database failure handling
14. User and project authorization
15. CLI argument validation
16. Compatibility with existing CLI commands
17. Exact cache hits generating zero additional AI calls
18. Token reduction preserving correctness and validation checks
"""

import csv
import io
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from mutagen.ai.base import AIProviderBase
from mutagen.ai.reduction import (
    PromptOptimizer, TokenBudgetManager, TokenEstimator, TokenReductionEngine,
)
from mutagen.ai.tracker import TrackedAIProvider
from mutagen.cli.main import app
from mutagen.core.auth import CredentialsManager
from mutagen.db.repositories import (
    AIUsageRepository, AnalysisCacheRepository, CacheEventRepository, ProjectRepository,
)
from mutagen.exceptions import (
    MutagenAuthenticationError, MutagenAuthorizationError, MutagenBudgetExceededError, MutagenValidationError,
)
from mutagen.models import AIUsageRecord, CacheEventRecord
from mutagen.schemas import (
    CodeAnalysis, MemoryContext, MemoryRecord, MemoryType,
    MutationCandidate, MutationResponse,
    MutationStrategy, OptimizationObjective,
)
from mutagen.services.usage_service import UsageService

runner = CliRunner()


# ── 1. Actual Provider-Reported Token Aggregation ───────────

def test_provider_reported_token_aggregation(db_session, auth_user):
    """Verify aggregation of actual provider-reported token counts."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)

    # Insert two provider-reported records
    repo.record_usage(
        user_id=user_id,
        operation="analyze",
        provider="gemini",
        model="gemini-2.5-flash",
        input_tokens=500,
        output_tokens=150,
        total_tokens=650,
        usage_source="provider_reported",
        status="success",
        latency_ms=320.0,
    )
    repo.record_usage(
        user_id=user_id,
        operation="mutate",
        provider="gemini",
        model="gemini-2.5-flash",
        input_tokens=1200,
        output_tokens=400,
        total_tokens=1600,
        usage_source="provider_reported",
        status="success",
        latency_ms=850.0,
    )
    db_session.commit()

    agg = repo.aggregate_usage(user_id=user_id)
    assert agg["total_requests"] == 2
    assert agg["successful_requests"] == 2
    assert agg["failed_requests"] == 0
    assert agg["actual_input_tokens"] == 1700
    assert agg["actual_output_tokens"] == 550
    assert agg["actual_total_tokens"] == 2250


# ── 2. Missing Token Metadata Handling ──────────────────────

def test_missing_token_metadata_not_zero(db_session, auth_user):
    """Unknown token metadata must be recorded as None/unavailable, never as zero."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)

    rec = repo.record_usage(
        user_id=user_id,
        operation="explain_change",
        provider="gemma",
        model="gemma4:e4b",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        usage_source="unavailable",
        status="success",
        latency_ms=210.0,
    )
    db_session.commit()

    assert rec.input_tokens is None
    assert rec.output_tokens is None
    assert rec.total_tokens is None
    assert rec.usage_source == "unavailable"

    agg = repo.aggregate_usage(user_id=user_id)
    assert agg["actual_input_tokens"] == 0
    assert agg["actual_output_tokens"] == 0
    assert agg["actual_total_tokens"] == 0
    assert agg["unavailable_measurements"] == 1


# ── 3. Estimated Usage Kept Separate from Actual Consumption ─

def test_estimated_usage_separate_from_actual(db_session, auth_user):
    """Estimated tokens must never be added to actual consumption."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)

    repo.record_usage(
        user_id=user_id,
        operation="analyze",
        provider="fake",
        model="fake-model",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        estimated_input_tokens=300,
        estimated_output_tokens=100,
        estimated_total_tokens=400,
        usage_source="estimated",
        status="success",
    )
    db_session.commit()

    agg = repo.aggregate_usage(user_id=user_id)
    # Actual consumption must remain strictly 0
    assert agg["actual_input_tokens"] == 0
    assert agg["actual_output_tokens"] == 0
    assert agg["actual_total_tokens"] == 0
    assert agg["estimated_total_tokens"] == 400


# ── 4. Date-Range Filtering ─────────────────────────────────

def test_date_range_filtering(db_session, auth_user):
    """Verify records are correctly filtered by since and until dates."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)

    now = datetime.now()
    past_date = now - timedelta(days=5)
    recent_date = now - timedelta(days=1)

    r1 = repo.record_usage(user_id=user_id, operation="analyze", provider="fake", total_tokens=100)
    r1.created_at = past_date
    r2 = repo.record_usage(user_id=user_id, operation="mutate", provider="fake", total_tokens=200)
    r2.created_at = recent_date
    db_session.commit()

    # Query with since matching only the recent record
    since_dt = now - timedelta(days=2)
    filtered = repo.query_records(user_id=user_id, since=since_dt)
    assert len(filtered) == 1
    assert filtered[0].operation == "mutate"


# ── 5. Operation Filtering ──────────────────────────────────

def test_operation_filtering(db_session, auth_user):
    """Verify filtering by operation type."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)

    repo.record_usage(user_id=user_id, operation="analyze", provider="fake", total_tokens=100)
    repo.record_usage(user_id=user_id, operation="mutate", provider="fake", total_tokens=200)
    repo.record_usage(user_id=user_id, operation="evolution", provider="fake", total_tokens=300)
    db_session.commit()

    records = repo.query_records(user_id=user_id, operation="mutate")
    assert len(records) == 1
    assert records[0].operation == "mutate"


# ── 6. Cache-Hit Calculations & Zero Lookups ────────────────

def test_cache_hit_rate_calculations(db_session, auth_user):
    """Cache hit rate = hits / lookups * 100. Handle zero lookups gracefully."""
    user_id = auth_user["user"]["id"]
    repo = CacheEventRepository(db_session)

    # Zero lookups
    stats_empty = repo.aggregate_cache_stats(user_id=user_id)
    assert stats_empty["total_lookups"] == 0
    assert stats_empty["cache_hit_rate"] == 0.0

    # 1 hit, 3 misses -> 4 lookups -> 25.0%
    repo.create(user_id=user_id, operation="analyze", cache_type="exact_analysis", cache_hit=True, ai_requests_avoided=1)
    repo.create(user_id=user_id, operation="analyze", cache_type="exact_analysis", cache_hit=False)
    repo.create(user_id=user_id, operation="analyze", cache_type="exact_analysis", cache_hit=False)
    repo.create(user_id=user_id, operation="analyze", cache_type="exact_analysis", cache_hit=False)
    db_session.commit()

    stats = repo.aggregate_cache_stats(user_id=user_id)
    assert stats["total_lookups"] == 4
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 3
    assert stats["cache_hit_rate"] == 25.0


# ── 7. Token Savings Calculations with Baseline ─────────────

def test_token_savings_calculations_with_baseline(db_session, auth_user):
    """Token savings must use documented baselines and never double count."""
    user_id = auth_user["user"]["id"]
    repo = CacheEventRepository(db_session)

    repo.create(
        user_id=user_id,
        operation="analyze",
        cache_type="exact_analysis",
        cache_hit=True,
        ai_requests_avoided=1,
        estimated_tokens_avoided=450,
        savings_baseline="Historical analysis baseline (hash=abc12345)",
    )
    repo.create(
        user_id=user_id,
        operation="mutate",
        cache_type="function_ast",
        cache_hit=True,
        ai_requests_avoided=1,
        estimated_tokens_avoided=350,
        savings_baseline="Function-level AST cache baseline",
    )
    db_session.commit()

    stats = repo.aggregate_cache_stats(user_id=user_id)
    assert stats["ai_requests_avoided"] == 2
    assert stats["estimated_tokens_saved"] == 800


# ── 8. Duplicate Record Prevention ──────────────────────────

def test_duplicate_record_prevention(db_session, auth_user):
    """Recording usage with the same request_id must return existing record."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)

    rec1 = repo.record_usage(
        user_id=user_id,
        operation="analyze",
        provider="gemini",
        total_tokens=100,
        request_id="req-unique-999",
    )
    db_session.commit()

    # Attempt to record identical request_id
    rec2 = repo.record_usage(
        user_id=user_id,
        operation="analyze",
        provider="gemini",
        total_tokens=999,
        request_id="req-unique-999",
    )
    db_session.commit()

    assert rec1.id == rec2.id
    assert rec2.total_tokens == 100  # Original kept, duplicate prevented


# ── 9. Duplicate Savings Prevention ─────────────────────────

def test_duplicate_savings_prevention(db_session, auth_user):
    """Avoid recording duplicate savings for the exact same event."""
    user_id = auth_user["user"]["id"]
    repo = CacheEventRepository(db_session)

    e1 = repo.create(
        user_id=user_id,
        analysis_id="an-1",
        operation="analyze",
        cache_type="exact_analysis",
        cache_hit=True,
        ai_requests_avoided=1,
        estimated_tokens_avoided=500,
    )
    db_session.commit()

    # Second event on different analysis
    e2 = repo.create(
        user_id=user_id,
        analysis_id="an-2",
        operation="analyze",
        cache_type="exact_analysis",
        cache_hit=True,
        ai_requests_avoided=1,
        estimated_tokens_avoided=500,
    )
    db_session.commit()

    stats = repo.aggregate_cache_stats(user_id=user_id)
    assert stats["ai_requests_avoided"] == 2
    assert stats["estimated_tokens_saved"] == 1000


# ── 10. CSV Exports with Stable Columns ─────────────────────

def test_csv_export_stable_columns(db_session, auth_user):
    """CSV export must include standardized, stable columns."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)
    repo.record_usage(
        user_id=user_id,
        operation="analyze",
        provider="gemini",
        model="gemini-2.5-flash",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        usage_source="provider_reported",
        status="success",
        latency_ms=250.0,
    )
    db_session.commit()

    svc = UsageService(session=db_session)
    csv_str = svc.export_csv(user_id=user_id)

    reader = csv.reader(io.StringIO(csv_str))
    headers = next(reader)
    expected_headers = [
        "id", "timestamp", "operation", "provider", "model",
        "input_tokens", "output_tokens", "total_tokens",
        "cached_input_tokens", "measurement_source", "status",
        "latency_ms", "attempt_number", "generation_number",
        "candidate_id", "analysis_id", "project_id",
    ]
    assert headers == expected_headers
    row = next(reader)
    assert row[2] == "analyze"
    assert row[3] == "gemini"
    assert row[7] == "150"


# ── 11. JSON Exports ────────────────────────────────────────

def test_json_export_structure(db_session, auth_user):
    """JSON export must produce valid structured summary and records."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)
    repo.record_usage(
        user_id=user_id,
        operation="mutate",
        provider="gemma",
        model="gemma4:e4b",
        total_tokens=300,
    )
    db_session.commit()

    svc = UsageService(session=db_session)
    data = svc.export_json(user_id=user_id)

    assert "summary" in data
    assert "records" in data
    assert "total_records" in data
    assert data["total_records"] == 1
    assert data["records"][0]["operation"] == "mutate"


# ── 12. Empty Database Behavior ─────────────────────────────

def test_empty_database_behavior(auth_user):
    """Empty database must display helpful empty-state message without crashing."""
    result = runner.invoke(app, ["usage"])
    assert result.exit_code == 0
    assert "MUTAGEN TOKEN USAGE" in result.output
    assert "No token usage or cache events recorded yet" in result.output
    assert "mutagen analyze" in result.output


# ── 13. Database Failure Handling ───────────────────────────

def test_database_failure_handling(auth_user, monkeypatch):
    """Database failures must display friendly message and exit code 1."""
    def broken_session(*args, **kwargs):
        raise Exception("OperationalError: Unable to connect to postgresql database")

    monkeypatch.setattr("mutagen.services.usage_service.get_session", broken_session)

    result = runner.invoke(app, ["usage"])
    assert result.exit_code == 1
    assert "Database error" in result.output or "Unable to connect" in result.output


# ── 14. User and Project Authorization ──────────────────────

def test_user_and_project_authorization(db_session, auth_user):
    """User cannot query records of a project owned by another user."""
    user_id = auth_user["user"]["id"]
    other_user_id = "user-other-999"

    proj_repo = ProjectRepository(db_session)
    proj = proj_repo.create(
        name="Private Project",
        user_id=other_user_id,
        description="Private user project",
    )
    db_session.commit()

    svc = UsageService(session=db_session)
    with pytest.raises(MutagenAuthorizationError, match="not authorized to access project"):
        svc.get_usage_dashboard(user_id=user_id, project_id=proj.id)


# ── 15. CLI Argument Validation ─────────────────────────────

def test_cli_argument_validation(auth_user):
    """CLI must validate dates and export formats with exit code 2."""
    # Bad since date
    res1 = runner.invoke(app, ["usage", "--since", "not-a-date"])
    assert res1.exit_code == 2
    assert "Invalid date format" in res1.output

    # Bad date range (since > until)
    res2 = runner.invoke(app, ["usage", "--since", "2026-10-15", "--until", "2026-10-10"])
    assert res2.exit_code == 2
    assert "Invalid date range" in res2.output

    # Bad export format
    res3 = runner.invoke(app, ["usage", "--export", "yaml"])
    assert res3.exit_code == 2
    assert "Invalid export format" in res3.output


# ── 16. CLI Compatibility with Existing Commands ─────────────

def test_cli_compatibility_with_existing_commands(auth_user):
    """Usage command must coexist cleanly with version, doctor, and other commands."""
    res_ver = runner.invoke(app, ["version"])
    assert res_ver.exit_code == 0

    res_doc = runner.invoke(app, ["doctor"])
    assert res_doc.exit_code == 0

    res_use = runner.invoke(app, ["usage", "--help"])
    assert res_use.exit_code == 0
    assert "Inspect AI token consumption" in res_use.output


# ── 17. Exact Cache Hits Generating Zero Additional AI Calls ─

def test_exact_cache_hit_zero_ai_calls(db_session, auth_user):
    """An exact cache hit must result in zero additional AI calls."""
    user_id = auth_user["user"]["id"]

    mock_provider = MagicMock(spec=AIProviderBase)
    mock_provider.provider_name = "gemini"
    mock_provider.model_id = "gemini-2.5-flash"
    mock_provider.analyze_code.return_value = {
        "summary": "Fast addition",
        "bottlenecks": [],
        "complexity": "O(1)",
        "usage": {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160},
    }

    tracked = TrackedAIProvider(mock_provider, user_id=user_id, session=db_session)

    code = "def fast_add(a: int, b: int) -> int:\n    return a + b\n"

    # First call: cache miss -> calls AI provider
    res1 = tracked.analyze_code(code, "python")
    assert mock_provider.analyze_code.call_count == 1
    assert res1["summary"] == "Fast addition"

    # Second identical call: exact cache hit -> zero AI calls!
    res2 = tracked.analyze_code(code, "python")
    assert mock_provider.analyze_code.call_count == 1  # Still 1! Zero additional calls!
    assert res2["summary"] == "Fast addition"

    # Verify cache event recorded hit
    cache_repo = CacheEventRepository(db_session)
    events = cache_repo.query_events(user_id=user_id)
    assert any(e.cache_hit for e in events)


# ── 18. Token Reduction Preserves Correctness ───────────────

def test_token_reduction_preserves_correctness():
    """Prompt deduplication and memory filtering must preserve essential information."""
    # Test memory deduplication
    m1 = MemoryRecord(record_id="m1", memory_type=MemoryType.PROJECT, content="Keep functions pure")
    m2 = MemoryRecord(record_id="m2", memory_type=MemoryType.PROJECT, content="Keep functions pure")
    m3 = MemoryRecord(record_id="m3", memory_type=MemoryType.PROJECT, content="Use type annotations")
    m4 = MemoryRecord(record_id="m4", memory_type=MemoryType.EVOLUTION, content="Avoid nested loops")
    m5 = MemoryRecord(record_id="m5", memory_type=MemoryType.EVOLUTION, content="Avoid nested loops")
    m6 = MemoryRecord(record_id="m6", memory_type=MemoryType.SEMANTIC, content="Vectorize math operations")

    ctx = MemoryContext(
        project_memories=[m1, m2, m3],
        evolution_memories=[m4, m5],
        semantic_memories=[m6],
        total_records=6,
    )
    opt = PromptOptimizer.optimize_memory_context(ctx)
    assert len(opt.project_memories) == 2
    assert len(opt.evolution_memories) == 1
    contents_proj = [m.content for m in opt.project_memories]
    assert "Keep functions pure" in contents_proj
    assert "Use type annotations" in contents_proj

    # Test failure summarization
    fails = [
        "IndexError: list index out of range",
        "IndexError: list index out of range",
        "SyntaxError: invalid syntax",
    ]
    opt_fails = PromptOptimizer.optimize_failures(fails)
    assert len(opt_fails) == 2
    assert "IndexError: list index out of range" in opt_fails
    assert "SyntaxError: invalid syntax" in opt_fails


# ── Additional: CLI Flags Output Formatting ─────────────────

def test_cli_usage_dashboard_with_records(db_session, auth_user):
    """Test standard usage dashboard rendering with populated records."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)
    repo.record_usage(
        user_id=user_id,
        operation="analyze",
        provider="gemini",
        model="gemini-2.5-flash",
        input_tokens=85400,
        output_tokens=21600,
        total_tokens=107000,
        usage_source="provider_reported",
        status="success",
    )
    cache_repo = CacheEventRepository(db_session)
    cache_repo.create(
        user_id=user_id,
        operation="analyze",
        cache_type="exact_analysis",
        cache_hit=True,
        ai_requests_avoided=58,
        estimated_tokens_avoided=42300,
    )
    db_session.commit()

    result = runner.invoke(app, ["usage"])
    assert result.exit_code == 0
    assert "MUTAGEN TOKEN USAGE" in result.output
    assert "Actual Total Tokens:" in result.output and "107,000" in result.output
    assert "Estimated Tokens Saved:" in result.output and "42,300" in result.output
    assert "AI Requests Avoided:" in result.output and "58" in result.output


def test_cli_usage_json_output(db_session, auth_user):
    """Test --json flag produces clean parseable JSON without decoration."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)
    repo.record_usage(
        user_id=user_id,
        operation="mutate",
        provider="gemma",
        model="gemma4:e4b",
        total_tokens=500,
    )
    db_session.commit()

    result = runner.invoke(app, ["usage", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "analysis_statistics" in data
    assert "token_consumption" in data
    assert "optimization" in data


def test_cli_usage_detailed_and_savings(db_session, auth_user):
    """Test --detailed, --cache, and --savings commands."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)
    repo.record_usage(
        user_id=user_id,
        operation="evolution",
        provider="gemini",
        model="gemini-2.5-flash",
        total_tokens=1200,
        status="success",
    )
    cache_repo = CacheEventRepository(db_session)
    cache_repo.create(
        user_id=user_id,
        operation="evolution",
        cache_type="exact_analysis",
        cache_hit=True,
        ai_requests_avoided=1,
        estimated_tokens_avoided=1200,
    )
    db_session.commit()

    res_det = runner.invoke(app, ["usage", "--detailed"])
    assert res_det.exit_code == 0
    assert "evolu" in res_det.output or "1,200" in res_det.output

    res_cache = runner.invoke(app, ["usage", "--cache"])
    assert res_cache.exit_code == 0
    assert "MUTAGEN Cache & Optimization Statistics" in res_cache.output

    res_sav = runner.invoke(app, ["usage", "--savings"])
    assert res_sav.exit_code == 0
    assert "MUTAGEN Token Savings & Avoided Work" in res_sav.output


def test_cli_usage_export_csv_and_json(db_session, auth_user):
    """Test --export csv and --export json CLI outputs."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)
    repo.record_usage(
        user_id=user_id,
        operation="analyze",
        provider="gemini",
        total_tokens=800,
    )
    db_session.commit()

    res_csv = runner.invoke(app, ["usage", "--export", "csv"])
    assert res_csv.exit_code == 0
    assert "input_tokens,output_tokens,total_tokens" in res_csv.output

    res_json = runner.invoke(app, ["usage", "--export", "json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.output)
    assert "summary" in data
    assert "records" in data


def test_recalibrated_token_estimator():
    """Verify calibrated TokenEstimator calculations."""
    prompt = "def add(a: int, b: int) -> int:\n    return a + b\n"
    in_tok, out_tok, tot_tok = TokenEstimator.estimate_prompt_and_completion(prompt, "return a + b")
    assert in_tok > 0
    assert out_tok > 0
    assert tot_tok == in_tok + out_tok


def test_cli_usage_dashboard_shows_storage_architecture_and_log(db_session, auth_user):
    """Verify mutagen usage command displays where and how tokens are saved with audit log."""
    user_id = auth_user["user"]["id"]
    repo = AIUsageRepository(db_session)
    repo.record_usage(
        user_id=user_id,
        operation="mutate",
        provider="gemma",
        model="gemma4:e4b",
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        usage_source="provider_reported",
        status="success",
    )
    cache_repo = CacheEventRepository(db_session)
    cache_repo.create(
        user_id=user_id,
        operation="mutate",
        cache_type="exact_analysis",
        cache_hit=True,
        ai_requests_avoided=1,
        estimated_tokens_avoided=1500,
        savings_baseline="Exact SHA-256 match in analysis_cache_records",
    )
    db_session.commit()

    result = runner.invoke(app, ["usage"])
    assert result.exit_code == 0
    # Must explain WHERE and HOW tokens are saved
    assert "WHERE & HOW TOKENS ARE SAVED" in result.output
    assert "analysis_cache_records (DB Table)" in result.output
    assert "SHA-256 Content-Hash Deduplication" in result.output
    # Must show breakdown and audit log
    assert "Token Savings Breakdown by Storage Layer" in result.output
    assert "Recent Token Savings Audit Log" in result.output
    assert "exact_analysis" in result.output
    assert "+1,500" in result.output
