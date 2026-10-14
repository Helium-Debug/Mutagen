"""
Central Token Reduction & Optimization Engine for MUTAGEN.

Integrates with MUTAGEN's Smart Memory Engine to actively reduce AI token consumption:
1. Exact Analysis Cache: Reuses valid cached results for identical content hashes (zero AI calls).
2. Deterministic Analysis: Satisfies tasks statically when AST analysis is sufficient.
3. Incremental Analysis: Reuses function-level analysis for unchanged AST nodes.
4. Prompt Optimization: Deduplicates memory records, prunes redundant context, minimizes prompts.
5. Budget Management: Enforces per-request, per-analysis, daily, monthly, and project budgets.
6. Centralized Usage Tracking: Records provider-reported tokens, estimated usage, and latency.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Union

from mutagen.analysis.python_analyzer import PythonAnalyzer
from mutagen.config import get_settings
from mutagen.core.identifiers import generate_id, utc_now
from mutagen.core.logging import get_logger
from mutagen.core.security import compute_content_hash
from mutagen.db.repositories import (
    AIUsageRepository, CacheEventRepository, AnalysisCacheRepository,
)
from mutagen.db.session import get_session
from mutagen.exceptions import MutagenBudgetExceededError, MutagenError
from mutagen.schemas import (
    CodeAnalysis, MemoryContext, MemoryRecord, MutationResponse, OptimizationObjective,
)

logger = get_logger("ai.reduction")


class TokenEstimator:
    """
    Estimates token counts for prompts and completions when providers
    do not expose token metadata or before requests are dispatched.
    """

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Estimate tokens for code and natural language text.
        
        Uses an accurate empirical heuristic: ~3.8 characters per token for code/JSON,
        accounting for whitespace, indentation, punctuation, and identifiers.
        """
        if not text:
            return 0
        cleaned = text.strip()
        if not cleaned:
            return 0

        # Calibrated empirical ratio for code and mixed prompts: ~3.5 chars/token
        char_count = len(cleaned)
        word_count = len(re.findall(r"\w+|[^\w\s]", cleaned))
        
        # Blended estimate between word/punctuation count and char length
        estimated = int(math.ceil((char_count / 3.5 + word_count * 1.1) / 2.0))
        return max(1, estimated)

    @staticmethod
    def estimate_prompt_and_completion(prompt: str, completion: Optional[str] = None) -> tuple[int, int, int]:
        """Returns (estimated_input, estimated_output, estimated_total)."""
        input_tok = TokenEstimator.estimate_tokens(prompt)
        output_tok = TokenEstimator.estimate_tokens(completion) if completion else 250
        return input_tok, output_tok, input_tok + output_tok


class TokenBudgetManager:
    """
    Manages and enforces configurable token and request limits.
    """

    @staticmethod
    def check_request_budget(
        session,
        estimated_tokens: int,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        analysis_id: Optional[str] = None,
    ) -> None:
        """
        Check whether an upcoming AI request fits within all configured budgets.

        Raises:
            MutagenBudgetExceededError: If any configured limit is exceeded.
        """
        settings = get_settings()

        # 1. Per-request token budget
        if settings.token_budget_per_request is not None:
            if estimated_tokens > settings.token_budget_per_request:
                raise MutagenBudgetExceededError(
                    f"Request size ({estimated_tokens:,} estimated tokens) exceeds configured "
                    f"per-request token budget of {settings.token_budget_per_request:,} tokens."
                )

        usage_repo = AIUsageRepository(session)

        # 2. Per-analysis / per-experiment limits
        if analysis_id:
            if settings.max_requests_per_analysis is not None:
                analysis_records = usage_repo.query_records(
                    user_id=user_id,
                    project_id=project_id,
                    limit=1000,
                )
                req_count = sum(1 for r in analysis_records if r.analysis_id == analysis_id or r.experiment_id == analysis_id)
                if req_count >= settings.max_requests_per_analysis:
                    raise MutagenBudgetExceededError(
                        f"Analysis '{analysis_id}' reached maximum request limit of "
                        f"{settings.max_requests_per_analysis} requests."
                    )

            if settings.token_budget_per_analysis is not None:
                exp_totals = usage_repo.total_for_experiment(analysis_id)
                current_tokens = exp_totals.get("total_tokens", 0)
                if current_tokens + estimated_tokens > settings.token_budget_per_analysis:
                    raise MutagenBudgetExceededError(
                        f"Analysis '{analysis_id}' reached token limit: "
                        f"{current_tokens:,} consumed + {estimated_tokens:,} requested > "
                        f"{settings.token_budget_per_analysis:,} max tokens per analysis."
                    )

        # 3. Daily usage budget
        if settings.daily_token_budget is not None:
            now = datetime.now(timezone.utc)
            today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
            agg = usage_repo.aggregate_usage(user_id=user_id, since=today_start)
            today_total = agg.get("actual_total_tokens", 0)
            if today_total + estimated_tokens > settings.daily_token_budget:
                raise MutagenBudgetExceededError(
                    f"Daily token budget of {settings.daily_token_budget:,} reached. "
                    f"Consumed today: {today_total:,} tokens. "
                    "Wait until tomorrow or increase DAILY_TOKEN_BUDGET."
                )

        # 4. Monthly usage budget
        if settings.monthly_token_budget is not None:
            now = datetime.now(timezone.utc)
            month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            agg = usage_repo.aggregate_usage(user_id=user_id, since=month_start)
            month_total = agg.get("actual_total_tokens", 0)
            if month_total + estimated_tokens > settings.monthly_token_budget:
                raise MutagenBudgetExceededError(
                    f"Monthly token budget of {settings.monthly_token_budget:,} reached. "
                    f"Consumed this month: {month_total:,} tokens."
                )

        # 5. Project token budget
        if project_id and settings.project_token_budget is not None:
            agg = usage_repo.aggregate_usage(user_id=user_id, project_id=project_id)
            proj_total = agg.get("actual_total_tokens", 0)
            if proj_total + estimated_tokens > settings.project_token_budget:
                raise MutagenBudgetExceededError(
                    f"Project '{project_id}' token budget of {settings.project_token_budget:,} reached. "
                    f"Consumed: {proj_total:,} tokens."
                )


class PromptOptimizer:
    """
    Minimizes prompt size without losing correctness or semantics.
    """

    @staticmethod
    def optimize_memory_context(memory_context: Optional[MemoryContext]) -> Optional[MemoryContext]:
        """
        Deduplicate memory items, remove empty entries, and bound context length.
        """
        if not memory_context:
            return None

        def deduplicate(records: list[MemoryRecord], max_items: int = 3) -> list[MemoryRecord]:
            seen_content = set()
            unique_records = []
            for r in records:
                norm = r.content.strip().lower()
                if norm and norm not in seen_content:
                    seen_content.add(norm)
                    unique_records.append(r)
                if len(unique_records) >= max_items:
                    break
            return unique_records

        opt_project = deduplicate(memory_context.project_memories, max_items=3)
        opt_evolution = deduplicate(memory_context.evolution_memories, max_items=3)
        opt_semantic = deduplicate(memory_context.semantic_memories, max_items=3)

        total = len(opt_project) + len(opt_evolution) + len(opt_semantic)
        return MemoryContext(
            project_memories=opt_project,
            evolution_memories=opt_evolution,
            semantic_memories=opt_semantic,
            total_records=total,
        )

    @staticmethod
    def optimize_failures(previous_failures: Optional[list[str]], max_items: int = 3) -> list[str]:
        """
        Deduplicate previous failure summaries and summarize concisely.
        """
        if not previous_failures:
            return []

        seen = set()
        clean = []
        for fail in reversed(previous_failures):
            # Extract essential diagnostic message
            msg = fail.strip()
            # Collapse multiple whitespace
            msg = re.sub(r"\s+", " ", msg)
            if len(msg) > 150:
                msg = msg[:147] + "..."
            norm = msg.lower()
            if norm not in seen:
                seen.add(norm)
                clean.append(msg)
            if len(clean) >= max_items:
                break
        clean.reverse()
        return clean


class TokenReductionEngine:
    """
    Coordinates token reduction and caching across MUTAGEN:
    - Exact Cache
    - Deterministic Analysis
    - Incremental Function-Level Cache
    - Token Tracking & Savings Accounting
    """

    def __init__(self, session=None, user_id: Optional[str] = None):
        self._session = session
        self.user_id = user_id
        self.settings = get_settings()

    def set_session(self, session) -> None:
        """Set active session for transaction coordination."""
        self._session = session

    def _get_session(self):
        if self._session:
            return self._session
        return get_session()

    def check_exact_cache(
        self,
        content_hash: str,
        operation: str,
        language: str = "python",
        objective: str = "balanced",
        symbol_name: Optional[str] = None,
        project_id: Optional[str] = None,
        analysis_id: Optional[str] = None,
    ) -> tuple[bool, Optional[dict]]:
        """
        Check for an exact compatible cached result by content hash.
        
        Returns:
            Tuple of (is_cache_hit, cached_result_json).
            If exact cache hit, records cache hit event and returns cached JSON.
        """
        if not self.settings.enable_exact_cache:
            return False, None

        try:
            with self._get_context_session() as session:
                cache_repo = AnalysisCacheRepository(session)
                cached = cache_repo.get_exact(
                    content_hash=content_hash,
                    operation=operation,
                    language=language,
                    objective=objective,
                    symbol_name=symbol_name,
                    user_id=self.user_id,
                )

                event_repo = CacheEventRepository(session)

                if cached:
                    # EXACT CACHE HIT!
                    if cached.total_tokens and cached.total_tokens > 0:
                        tokens_avoided = cached.total_tokens
                    else:
                        in_tok = cached.input_tokens or (TokenEstimator.estimate_tokens(content_hash) + 350)
                        out_tok = cached.output_tokens or (TokenEstimator.estimate_tokens(json.dumps(cached.result_json)) if cached.result_json else 250)
                        tokens_avoided = in_tok + out_tok
                    baseline = f"AnalysisCacheRecord in database (hash={cached.content_hash[:8]}, op={cached.operation})"

                    event_repo.create(
                        user_id=self.user_id,
                        project_id=project_id,
                        analysis_id=analysis_id,
                        operation=operation,
                        cache_type="exact_analysis",
                        cache_hit=True,
                        ai_requests_avoided=1,
                        estimated_tokens_avoided=tokens_avoided,
                        savings_baseline=baseline,
                        reused_record_id=cached.id,
                    )
                    session.commit()
                    logger.info(
                        f"Exact cache hit for {operation} (hash={content_hash[:8]}). "
                        f"Avoided 1 AI call, saved ~{tokens_avoided} tokens."
                    )
                    return True, cached.result_json

                # EXACT CACHE MISS
                event_repo.create(
                    user_id=self.user_id,
                    project_id=project_id,
                    analysis_id=analysis_id,
                    operation=operation,
                    cache_type="exact_analysis",
                    cache_hit=False,
                    ai_requests_avoided=0,
                    estimated_tokens_avoided=0,
                )
                session.commit()
                return False, None
        except Exception as e:
            logger.warning(f"Exact cache lookup/recording failed ({e}); proceeding with fresh execution.")
            if self._session:
                try:
                    self._session.rollback()
                except Exception:
                    pass
            return False, None

    def store_cache_result(
        self,
        content_hash: str,
        operation: str,
        result_json: dict,
        language: str = "python",
        objective: str = "balanced",
        symbol_name: Optional[str] = None,
        project_id: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
    ) -> None:
        """Persist result in exact analysis cache."""
        if not self.settings.enable_exact_cache:
            return

        try:
            with self._get_context_session() as session:
                cache_repo = AnalysisCacheRepository(session)
                cache_repo.store(
                    content_hash=content_hash,
                    operation=operation,
                    result_json=result_json,
                    language=language,
                    objective=objective,
                    symbol_name=symbol_name,
                    user_id=self.user_id,
                    project_id=project_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )
                session.commit()
        except Exception as e:
            logger.warning(f"Storing cache result failed ({e}). Continuing.")
            if self._session:
                try:
                    self._session.rollback()
                except Exception:
                    pass

    def check_deterministic_analysis(
        self,
        source_code: str,
        language: str,
        operation: str,
        project_id: Optional[str] = None,
        analysis_id: Optional[str] = None,
    ) -> tuple[bool, Optional[dict]]:
        """
        Check whether deterministic static analysis satisfies the operation.
        
        For instance, if code has syntax errors or operation only requires static AST info,
        deterministic analysis avoids wasteful AI calls.
        """
        if language.lower() != "python":
            return False, None

        analyzer = PythonAnalyzer()
        is_valid, errors = analyzer.validate_syntax(source_code)
        if not is_valid:
            # Syntax is invalid: return deterministic error response without calling AI!
            res = {
                "language": language,
                "syntax_valid": False,
                "syntax_errors": errors,
                "deterministic": True,
                "structural_summary": {"functions": [], "classes": [], "public_interface": []},
                "complexity": {"estimated_time_complexity": "unknown"},
                "optimization_suggestions": [],
                "correctness_invariants": ["Code must be syntactically valid before mutation"],
            }
            try:
                with self._get_context_session() as session:
                    event_repo = CacheEventRepository(session)
                    event_repo.create(
                        user_id=self.user_id,
                        project_id=project_id,
                        analysis_id=analysis_id,
                        operation=operation,
                        cache_type="deterministic",
                        cache_hit=True,
                        ai_requests_avoided=1,
                        estimated_tokens_avoided=250,
                        savings_baseline="Deterministic AST syntax validation gate",
                    )
                    session.commit()
            except Exception as e:
                logger.warning(f"Failed to record deterministic cache event ({e}). Continuing.")
                if self._session:
                    try:
                        self._session.rollback()
                    except Exception:
                        pass
            return True, res

        return False, None

    def check_incremental_analysis(
        self,
        source_code: str,
        language: str,
        operation: str,
        objective: str = "balanced",
        project_id: Optional[str] = None,
        analysis_id: Optional[str] = None,
    ) -> tuple[bool, Optional[dict]]:
        """
        Check whether incremental function-level analysis can satisfy the task.
        Extracts AST functions and inspects if compatible cached analyses exist.
        """
        if not self.settings.enable_incremental_cache or language.lower() != "python":
            return False, None

        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return False, None

        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not functions:
            return False, None

        lines = source_code.splitlines()
        cached_functions = {}
        total_avoided = 0

        try:
            with self._get_context_session() as session:
                cache_repo = AnalysisCacheRepository(session)
                for fn in functions:
                    fn_lines = lines[fn.lineno - 1 : getattr(fn, "end_lineno", fn.lineno)]
                    fn_code = "\n".join(fn_lines)
                    fn_hash = compute_content_hash(fn_code)
                    cached = cache_repo.get_exact(
                        content_hash=fn_hash,
                        operation=operation,
                        language=language,
                        objective=objective,
                        symbol_name=fn.name,
                        user_id=self.user_id,
                    )
                    if cached:
                        cached_functions[fn.name] = cached.result_json
                        total_avoided += (cached.total_tokens or 100)

                # If all functions are cached, synthesize incremental response
                if len(cached_functions) == len(functions) and len(functions) > 0:
                    combined_suggestions = []
                    for name, data in cached_functions.items():
                        suggs = data.get("optimization_suggestions", [])
                        combined_suggestions.extend(suggs)

                    res = {
                        "language": language,
                        "incremental": True,
                        "functions_reused": list(cached_functions.keys()),
                        "structural_summary": {
                            "functions": [fn.name for fn in functions],
                            "classes": [],
                            "public_interface": [fn.name for fn in functions],
                        },
                        "complexity": {"estimated_time_complexity": "reused_from_incremental_cache"},
                        "optimization_suggestions": combined_suggestions,
                        "correctness_invariants": ["Preserved function-level interface contracts"],
                    }

                    event_repo = CacheEventRepository(session)
                    event_repo.create(
                        user_id=self.user_id,
                        project_id=project_id,
                        analysis_id=analysis_id,
                        operation=operation,
                        cache_type="incremental_analysis",
                        cache_hit=True,
                        ai_requests_avoided=1,
                        estimated_tokens_avoided=total_avoided,
                        savings_baseline=f"Reused {len(functions)} unchanged AST functions",
                    )
                    session.commit()
                    logger.info(
                        f"Incremental analysis hit for {len(functions)} functions in {operation}. "
                        f"Avoided 1 AI call, saved ~{total_avoided} tokens."
                    )
                    return True, res
        except Exception as e:
            logger.warning(f"Incremental cache check failed ({e}). Proceeding without incremental cache.")
            if self._session:
                try:
                    self._session.rollback()
                except Exception:
                    pass

        return False, None

    def record_usage(
        self,
        provider: str,
        model: str,
        operation: str,
        usage_data: Optional[dict] = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        analysis_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        generation_number: Optional[int] = None,
        attempt_number: int = 1,
        status: str = "success",
        error_message: Optional[str] = None,
        request_id: Optional[str] = None,
        latency_ms: int = 0,
        estimated_prompt: Optional[str] = None,
        estimated_completion: Optional[str] = None,
    ) -> None:
        """
        Record actual AI provider request usage.

        Accurately classifies:
        - provider_reported: Actual counts from provider usage metadata
        - estimated: When provider did not report, but estimated tokens are calculated
        - unavailable: When tokens could not be reported or estimated (never represented as zero)
        """
        uid = user_id or self.user_id
        exp_id = experiment_id or analysis_id

        input_tokens = None
        output_tokens = None
        total_tokens = None
        cached_input_tokens = 0
        estimated_input_tokens = None
        estimated_output_tokens = None
        estimated_total_tokens = None

        if usage_data:
            lat = usage_data.get("duration_ms", latency_ms)
            latency_ms = lat

            # Check if provider reported tokens
            has_input = "input_tokens" in usage_data and usage_data["input_tokens"] is not None
            has_output = "output_tokens" in usage_data and usage_data["output_tokens"] is not None
            has_total = "total_tokens" in usage_data and usage_data["total_tokens"] is not None

            if has_input or has_output or has_total:
                usage_source = "provider_reported"
                input_tokens = usage_data.get("input_tokens")
                output_tokens = usage_data.get("output_tokens")
                total_tokens = usage_data.get("total_tokens")
                if total_tokens is None and input_tokens is not None and output_tokens is not None:
                    total_tokens = input_tokens + output_tokens
                cached_input_tokens = usage_data.get("cached_input_tokens", 0)
            elif estimated_prompt:
                usage_source = "estimated"
                estimated_input_tokens = TokenEstimator.estimate_tokens(estimated_prompt)
                estimated_output_tokens = (
                    TokenEstimator.estimate_tokens(estimated_completion)
                    if estimated_completion
                    else (usage_data.get("output_tokens") or 250)
                )
                estimated_total_tokens = estimated_input_tokens + estimated_output_tokens
            else:
                usage_source = "unavailable"
        elif estimated_prompt:
            usage_source = "estimated"
            estimated_input_tokens = TokenEstimator.estimate_tokens(estimated_prompt)
            estimated_output_tokens = (
                TokenEstimator.estimate_tokens(estimated_completion)
                if estimated_completion
                else 250
            )
            estimated_total_tokens = estimated_input_tokens + estimated_output_tokens
        else:
            usage_source = "unavailable"

        try:
            with self._get_context_session() as session:
                usage_repo = AIUsageRepository(session)
                usage_repo.create(
                    user_id=uid,
                    project_id=project_id,
                    experiment_id=exp_id,
                    analysis_id=analysis_id or experiment_id,
                    candidate_id=candidate_id,
                    generation_number=generation_number,
                    attempt_number=attempt_number,
                    provider=provider,
                    model=model,
                    operation=operation,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cached_input_tokens=cached_input_tokens,
                    estimated_input_tokens=estimated_input_tokens,
                    estimated_output_tokens=estimated_output_tokens,
                    estimated_total_tokens=estimated_total_tokens,
                    usage_source=usage_source,
                    request_id=request_id or generate_id(),
                    status=status,
                    latency_ms=latency_ms,
                    duration_ms=latency_ms,
                    success=(status == "success"),
                    error_message=error_message,
                )
                session.commit()
        except Exception as e:
            logger.error(f"Failed to record AI usage record: {e}")
            if self._session:
                try:
                    self._session.rollback()
                except Exception:
                    pass

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
