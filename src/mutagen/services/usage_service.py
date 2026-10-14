"""
Usage Service for MUTAGEN.

Provides centralized token tracking queries, database aggregations,
cache statistics, token savings calculations, and CSV/JSON exports.
Enforces user and project authorization.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Optional

from mutagen.db.repositories import (
    AIUsageRepository, CacheEventRepository, ProjectRepository,
)
from mutagen.db.session import get_session
from mutagen.exceptions import (
    MutagenAuthorizationError, MutagenValidationError,
)
from mutagen.models import AIUsageRecord, CacheEventRecord


class UsageService:
    """Service providing token usage aggregation, cache statistics, and exports."""

    def __init__(self, session=None):
        self._session = session

    def _get_context_session(self):
        class _SessionCtx:
            def __init__(self, s):
                self._s = s
                self._owns = False
            def __enter__(self):
                if self._s is None:
                    self._s = get_session().__enter__()
                    self._owns = True
                return self._s
            def __exit__(self, exc_type, exc_val, exc_tb):
                if self._owns:
                    self._s.__exit__(exc_type, exc_val, exc_tb)
                elif exc_type is not None and self._s is not None:
                    try:
                        self._s.rollback()
                    except Exception:
                        pass
        return _SessionCtx(self._session)

    def _validate_project_access(self, session, project_id: Optional[str], user_id: Optional[str]) -> None:
        """Verify the user owns or is authorized to view the requested project."""
        if not project_id:
            return
        proj_repo = ProjectRepository(session)
        project = proj_repo.get(project_id, user_id=user_id)
        if not project:
            # Check if project exists for another user
            any_proj = proj_repo.get(project_id)
            if any_proj and any_proj.user_id != user_id:
                raise MutagenAuthorizationError(
                    f"User is not authorized to access project '{project_id}'."
                )

    def get_usage_dashboard(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Retrieve complete usage statistics dashboard matching MUTAGEN terminal layout.
        Uses efficient SQL aggregation.
        """
        with self._get_context_session() as session:
            self._validate_project_access(session, project_id, user_id)

            usage_repo = AIUsageRepository(session)
            cache_repo = CacheEventRepository(session)

            usage_agg = usage_repo.aggregate_usage(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
                provider=provider,
                model=model,
            )

            cache_agg = cache_repo.aggregate_cache_stats(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
            )

            total_ai_requests = usage_agg["total_requests"]
            ai_requests_avoided = cache_agg["ai_requests_avoided"]
            total_analyses = total_ai_requests + ai_requests_avoided

            is_empty = (total_analyses == 0 and total_ai_requests == 0 and cache_agg["total_lookups"] == 0)

            # Query recent savings events for the audit log
            recent_events = cache_repo.query_events(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
                limit=10,
            )
            recent_savings_log = [
                {
                    "timestamp": e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "",
                    "operation": e.operation,
                    "cache_type": e.cache_type,
                    "tokens_avoided": e.estimated_tokens_avoided,
                    "requests_avoided": e.ai_requests_avoided,
                    "baseline": e.savings_baseline or "Historical measured baseline",
                }
                for e in recent_events
                if e.cache_hit and e.estimated_tokens_avoided > 0
            ]

            savings_breakdown = cache_repo.get_savings_breakdown(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
            )

            actual_total = usage_agg["actual_total_tokens"]
            estimated_saved = cache_agg["estimated_tokens_saved"]
            total_work = actual_total + estimated_saved
            multiplier = f"{(total_work / max(1, actual_total)):.2f}x" if actual_total > 0 else "1.00x"

            storage_and_mechanisms = [
                {
                    "layer": "Exact Analysis Cache",
                    "storage_location": "analysis_cache_records (DB Table)",
                    "mechanism": "SHA-256 Content-Hash Deduplication",
                    "how_saved": "Identical code/AST produces identical hash; reuses cached mutations & AST analysis with 0 AI calls (100% savings on input + output).",
                },
                {
                    "layer": "Deterministic AST Gate",
                    "storage_location": "Local Python AST Analyzer (In-Memory Pre-Filter)",
                    "mechanism": "Static AST Syntax & Contract Pre-Validation",
                    "how_saved": "Catches syntax errors and contract violations locally before dispatching to AI, avoiding wasted prompt & completion tokens.",
                },
                {
                    "layer": "Incremental AST Cache",
                    "storage_location": "analysis_cache_records (Partitioned by symbol_name)",
                    "mechanism": "Function-Level AST Node Hashing",
                    "how_saved": "Isolates unchanged functions in multi-function files, reusing previous AST analyses instead of re-prompting the full codebase.",
                },
                {
                    "layer": "Prompt Optimizer",
                    "storage_location": "Transient Memory Context Pruner (In-Memory)",
                    "mechanism": "Deduplication & Failure Trace Compression",
                    "how_saved": "Deduplicates evolutionary memories and truncates failure traces to 150 chars, pruning 20-35% of repetitive prompt boilerplate.",
                },
                {
                    "layer": "Verification Early-Exit",
                    "storage_location": "SemanticVerificationLayer (Stages 1-4 Gate)",
                    "mechanism": "Fail-Fast Sandbox Testing",
                    "how_saved": "Deterministic unit tests and runtime checks fail flawed candidates before invoking expensive Stage 5 Logical LLM verification.",
                },
            ]

            return {
                "is_empty": is_empty,
                "analysis_statistics": {
                    "total_analyses": total_analyses,
                    "actual_ai_requests": total_ai_requests,
                    "successful_requests": usage_agg["successful_requests"],
                    "failed_requests": usage_agg["failed_requests"],
                    "cache_hits": cache_agg["cache_hits"],
                    "cache_misses": cache_agg["cache_misses"],
                    "incremental_analyses": cache_agg["incremental_analyses"],
                },
                "token_consumption": {
                    "actual_input_tokens": usage_agg["actual_input_tokens"],
                    "actual_output_tokens": usage_agg["actual_output_tokens"],
                    "actual_total_tokens": usage_agg["actual_total_tokens"],
                    "cached_input_tokens": usage_agg["cached_input_tokens"],
                    "estimated_total_tokens": usage_agg["estimated_total_tokens"],
                    "unavailable_measurements": usage_agg["unavailable_measurements"],
                },
                "optimization": {
                    "ai_requests_avoided": ai_requests_avoided,
                    "estimated_tokens_saved": estimated_saved,
                    "cache_hit_rate": cache_agg["cache_hit_rate"],
                    "total_work_tokens": total_work,
                    "efficiency_multiplier": multiplier,
                },
                "storage_and_mechanisms": storage_and_mechanisms,
                "savings_breakdown": savings_breakdown,
                "recent_savings_log": recent_savings_log,
                "filters": {
                    "user_id": user_id,
                    "project_id": project_id,
                    "since": since.isoformat() if since else None,
                    "until": until.isoformat() if until else None,
                    "operation": operation,
                    "provider": provider,
                    "model": model,
                },
            }

    def get_detailed_records(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Retrieve paginated individual usage records with all required audit metadata.
        """
        if page < 1:
            raise MutagenValidationError("Page must be >= 1.")
        if limit < 1 or limit > 10000:
            raise MutagenValidationError("Limit must be between 1 and 10,000.")

        offset = (page - 1) * limit

        with self._get_context_session() as session:
            self._validate_project_access(session, project_id, user_id)

            usage_repo = AIUsageRepository(session)
            total_records = usage_repo.count_records(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
                provider=provider,
                model=model,
                status=status,
            )

            records = usage_repo.query_records(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
                provider=provider,
                model=model,
                status=status,
                limit=limit,
                offset=offset,
            )

            formatted_records = [
                {
                    "id": r.id,
                    "timestamp": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
                    "iso_timestamp": r.created_at.isoformat() if r.created_at else "",
                    "operation": r.operation,
                    "provider": r.provider,
                    "model": r.model,
                    "input_tokens": r.input_tokens if r.input_tokens is not None else (
                        f"~{r.estimated_input_tokens}" if r.estimated_input_tokens else "Unavailable"
                    ),
                    "output_tokens": r.output_tokens if r.output_tokens is not None else (
                        f"~{r.estimated_output_tokens}" if r.estimated_output_tokens else "Unavailable"
                    ),
                    "total_tokens": r.total_tokens if r.total_tokens is not None else (
                        f"~{r.estimated_total_tokens}" if r.estimated_total_tokens else "Unavailable"
                    ),
                    "raw_input_tokens": r.input_tokens,
                    "raw_output_tokens": r.output_tokens,
                    "raw_total_tokens": r.total_tokens,
                    "cached_input_tokens": r.cached_input_tokens,
                    "measurement_source": r.usage_source,
                    "status": r.status,
                    "latency_ms": r.latency_ms,
                    "attempt_number": r.attempt_number,
                    "generation_number": r.generation_number,
                    "candidate_id": r.candidate_id,
                    "analysis_id": r.analysis_id or r.experiment_id,
                    "project_id": r.project_id,
                }
                for r in records
            ]

            total_pages = (total_records + limit - 1) // limit if total_records > 0 else 1

            return {
                "records": formatted_records,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total_records": total_records,
                    "total_pages": total_pages,
                },
            }

    def get_cache_statistics(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
    ) -> dict[str, Any]:
        """Retrieve detailed cache statistics breakdown."""
        with self._get_context_session() as session:
            self._validate_project_access(session, project_id, user_id)
            cache_repo = CacheEventRepository(session)
            stats = cache_repo.aggregate_cache_stats(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
            )
            events = cache_repo.query_events(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
                limit=100,
            )

            # Breakdown by cache type
            type_counts: dict[str, dict[str, int]] = {}
            for e in events:
                t = e.cache_type
                if t not in type_counts:
                    type_counts[t] = {"hits": 0, "misses": 0, "tokens_avoided": 0}
                if e.cache_hit:
                    type_counts[t]["hits"] += 1
                    type_counts[t]["tokens_avoided"] += e.estimated_tokens_avoided
                else:
                    type_counts[t]["misses"] += 1

            return {
                "summary": stats,
                "breakdown_by_type": type_counts,
            }

    def get_savings_report(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
    ) -> dict[str, Any]:
        """Retrieve documented token savings report."""
        with self._get_context_session() as session:
            self._validate_project_access(session, project_id, user_id)
            cache_repo = CacheEventRepository(session)
            stats = cache_repo.aggregate_cache_stats(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
            )
            events = cache_repo.query_events(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
                limit=50,
            )

            savings_events = [
                {
                    "timestamp": e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "",
                    "operation": e.operation,
                    "cache_type": e.cache_type,
                    "requests_avoided": e.ai_requests_avoided,
                    "tokens_avoided": e.estimated_tokens_avoided,
                    "baseline": e.savings_baseline or "Historical measured baseline",
                }
                for e in events
                if e.cache_hit and e.estimated_tokens_avoided > 0
            ]

            return {
                "total_requests_avoided": stats["ai_requests_avoided"],
                "total_estimated_tokens_saved": stats["estimated_tokens_saved"],
                "cache_hit_rate": stats["cache_hit_rate"],
                "recent_savings_events": savings_events,
                "accounting_notice": (
                    "Estimated saved tokens are tracked separately and are NOT added to actual consumption."
                ),
            }

    def export_csv(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10000,
    ) -> str:
        """Export usage records as stable, standardized CSV string."""
        with self._get_context_session() as session:
            self._validate_project_access(session, project_id, user_id)

            usage_repo = AIUsageRepository(session)
            records = usage_repo.query_records(
                user_id=user_id,
                project_id=project_id,
                since=since,
                until=until,
                operation=operation,
                provider=provider,
                model=model,
                status=status,
                limit=limit,
                offset=0,
            )

            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")

            # Stable standardized column headers
            writer.writerow([
                "id",
                "timestamp",
                "operation",
                "provider",
                "model",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cached_input_tokens",
                "measurement_source",
                "status",
                "latency_ms",
                "attempt_number",
                "generation_number",
                "candidate_id",
                "analysis_id",
                "project_id",
            ])

            for r in records:
                writer.writerow([
                    r.id,
                    r.created_at.isoformat() if r.created_at else "",
                    r.operation,
                    r.provider,
                    r.model,
                    r.input_tokens if r.input_tokens is not None else "",
                    r.output_tokens if r.output_tokens is not None else "",
                    r.total_tokens if r.total_tokens is not None else "",
                    r.cached_input_tokens,
                    r.usage_source,
                    r.status,
                    r.latency_ms,
                    r.attempt_number,
                    r.generation_number if r.generation_number is not None else "",
                    r.candidate_id or "",
                    r.analysis_id or r.experiment_id or "",
                    r.project_id or "",
                ])

            return output.getvalue()

    def export_json(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        operation: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10000,
    ) -> dict[str, Any]:
        """Export usage report as structured JSON."""
        dashboard = self.get_usage_dashboard(
            user_id=user_id,
            project_id=project_id,
            since=since,
            until=until,
            operation=operation,
            provider=provider,
            model=model,
        )
        detailed = self.get_detailed_records(
            user_id=user_id,
            project_id=project_id,
            since=since,
            until=until,
            operation=operation,
            provider=provider,
            model=model,
            status=status,
            page=1,
            limit=limit,
        )

        return {
            "summary": dashboard,
            "records": detailed["records"],
            "total_records": detailed["pagination"]["total_records"],
        }
