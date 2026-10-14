"""
Tracked AI Provider Wrapper for MUTAGEN.

Integrates centralized token tracking and active token reduction
into all AI provider operations (generate_mutations, analyze_code,
explain_change, explain_failure, summarize_experiment, etc.).
"""

from __future__ import annotations

import time
from typing import Optional, Union

from mutagen.ai.base import AIProviderBase
from mutagen.ai.reduction import (
    PromptOptimizer, TokenBudgetManager, TokenEstimator, TokenReductionEngine,
)
from mutagen.core.identifiers import generate_id, generate_mutation_id
from mutagen.core.logging import get_logger
from mutagen.core.security import compute_content_hash
from mutagen.db.session import get_session
from mutagen.schemas import (
    CodeAnalysis, MemoryContext, MutationCandidate, MutationResponse,
    MutationStrategy, OptimizationObjective,
)

logger = get_logger("ai.tracker")


class TrackedAIProvider(AIProviderBase):
    """
    Transparent decorator around any AIProviderBase that enforces:
    - Exact Cache Reuse (Zero AI calls on cache hit)
    - Deterministic & Incremental Analysis Checks
    - Context Deduplication and Prompt Minimization
    - Usage Budget Verification
    - Actual Provider Token Tracking and Latency Recording
    """

    def __init__(
        self,
        inner_provider: AIProviderBase,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        analysis_id: Optional[str] = None,
        session=None,
    ):
        self._inner = inner_provider
        self.user_id = user_id
        self.project_id = project_id
        self.analysis_id = analysis_id
        self._session = session
        self.engine = TokenReductionEngine(session=session, user_id=user_id)

    def set_session(self, session) -> None:
        """Propagate active session for transactional safety."""
        self._session = session
        if hasattr(self, "engine") and self.engine is not None:
            self.engine.set_session(session)

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    def check_availability(self) -> tuple[bool, str]:
        return self._inner.check_availability()

    def generate_mutations(
        self,
        source_code: str,
        language: str,
        analysis: CodeAnalysis,
        objective: OptimizationObjective,
        memory_context: Optional[MemoryContext] = None,
        previous_failures: Optional[list[str]] = None,
        candidate_count: int = 4,
        generation_number: Optional[int] = None,
    ) -> MutationResponse:
        """
        Generate mutation candidates with active token reduction and tracking.
        """
        source_hash = compute_content_hash(source_code)
        operation = "generate_mutations"

        # 1. Exact Cache Check
        is_hit, cached_data = self.engine.check_exact_cache(
            content_hash=source_hash,
            operation=operation,
            language=language,
            objective=objective.value,
            project_id=self.project_id,
            analysis_id=self.analysis_id,
        )
        if is_hit and cached_data:
            logger.info("Reusing exact cached mutation candidates (zero AI calls)")
            candidates = []
            for c in cached_data.get("candidates", []):
                cand_data = dict(c) if isinstance(c, dict) else c.model_dump()
                cand_data["candidate_id"] = generate_mutation_id()
                candidates.append(MutationCandidate(**cand_data))
            return MutationResponse(
                candidates=candidates,
                model_id=self._inner.model_id,
                usage={"cached": True, "total_tokens": 0},
            )

        # 2. Prompt Optimization
        opt_memory = PromptOptimizer.optimize_memory_context(memory_context)
        opt_failures = PromptOptimizer.optimize_failures(previous_failures)

        # 3. Budget Check
        est_tokens = TokenEstimator.estimate_tokens(source_code) + 500
        try:
            with self._get_context_session() as session:
                TokenBudgetManager.check_request_budget(
                    session=session,
                    estimated_tokens=est_tokens,
                    user_id=self.user_id,
                    project_id=self.project_id,
                    analysis_id=self.analysis_id,
                )
        except MutagenBudgetExceededError:
            raise
        except Exception as e:
            logger.warning(f"Budget check encountered non-fatal error: {e}")

        # 4. Actual Provider Call & Latency Measurement
        start_time = time.time()
        status = "success"
        error_msg = None
        response = None
        request_id = generate_id()

        try:
            response = self._inner.generate_mutations(
                source_code=source_code,
                language=language,
                analysis=analysis,
                objective=objective,
                memory_context=opt_memory,
                previous_failures=opt_failures,
                candidate_count=candidate_count,
            )
            return response
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            raise
        finally:
            latency_ms = int((time.time() - start_time) * 1000)
            usage_data = getattr(response, "usage", {}) if response else {}
            if usage_data is None:
                usage_data = {}

            # 5. Centralized Usage Tracking
            self.engine.record_usage(
                provider=self._inner.provider_name,
                model=self._inner.model_id,
                operation=operation,
                usage_data=usage_data,
                user_id=self.user_id,
                project_id=self.project_id,
                analysis_id=self.analysis_id,
                generation_number=generation_number,
                status=status,
                error_message=error_msg,
                request_id=request_id,
                latency_ms=latency_ms,
                estimated_prompt=source_code,
            )

            # 6. Store in Exact Cache on success
            if status == "success" and response and response.candidates:
                cand_dicts = [c.model_dump() for c in response.candidates]
                self.engine.store_cache_result(
                    content_hash=source_hash,
                    operation=operation,
                    result_json={"candidates": cand_dicts},
                    language=language,
                    objective=objective.value,
                    project_id=self.project_id,
                    input_tokens=usage_data.get("input_tokens"),
                    output_tokens=usage_data.get("output_tokens"),
                    total_tokens=usage_data.get("total_tokens"),
                )

    def analyze_code(
        self,
        source_code: str,
        language: str,
        objective: OptimizationObjective = OptimizationObjective.BALANCED,
        static_context: Optional[dict] = None,
    ) -> dict:
        """
        Analyze code with deterministic checks, exact caching, and incremental caching.
        """
        source_hash = compute_content_hash(source_code)
        operation = "analyze_code"

        # 1. Deterministic Analysis Check (Syntax validation / static AST)
        det_hit, det_result = self.engine.check_deterministic_analysis(
            source_code=source_code,
            language=language,
            operation=operation,
            project_id=self.project_id,
            analysis_id=self.analysis_id,
        )
        if det_hit and det_result:
            return det_result

        # 2. Exact Cache Check
        is_hit, cached_data = self.engine.check_exact_cache(
            content_hash=source_hash,
            operation=operation,
            language=language,
            objective=objective.value,
            project_id=self.project_id,
            analysis_id=self.analysis_id,
        )
        if is_hit and cached_data:
            return cached_data

        # 3. Incremental Analysis Check (Function-level AST)
        inc_hit, inc_result = self.engine.check_incremental_analysis(
            source_code=source_code,
            language=language,
            operation=operation,
            objective=objective.value,
            project_id=self.project_id,
            analysis_id=self.analysis_id,
        )
        if inc_hit and inc_result:
            return inc_result

        # 4. Budget Check
        est_tokens = TokenEstimator.estimate_tokens(source_code) + 300
        try:
            with self._get_context_session() as session:
                TokenBudgetManager.check_request_budget(
                    session=session,
                    estimated_tokens=est_tokens,
                    user_id=self.user_id,
                    project_id=self.project_id,
                    analysis_id=self.analysis_id,
                )
        except MutagenBudgetExceededError:
            raise
        except Exception as e:
            logger.warning(f"Budget check encountered non-fatal error: {e}")

        # 5. Actual Provider Call & Latency Measurement
        start_time = time.time()
        status = "success"
        error_msg = None
        result = None
        request_id = generate_id()

        try:
            result = self._inner.analyze_code(
                source_code=source_code,
                language=language,
                objective=objective,
                static_context=static_context,
            )
            return result
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            raise
        finally:
            latency_ms = int((time.time() - start_time) * 1000)
            usage_data = result.get("usage", {}) if isinstance(result, dict) else {}

            self.engine.record_usage(
                provider=self._inner.provider_name,
                model=self._inner.model_id,
                operation=operation,
                usage_data=usage_data,
                user_id=self.user_id,
                project_id=self.project_id,
                analysis_id=self.analysis_id,
                status=status,
                error_message=error_msg,
                request_id=request_id,
                latency_ms=latency_ms,
                estimated_prompt=source_code,
            )

            # 6. Store in Cache on success
            if status == "success" and isinstance(result, dict):
                self.engine.store_cache_result(
                    content_hash=source_hash,
                    operation=operation,
                    result_json=result,
                    language=language,
                    objective=objective.value,
                    project_id=self.project_id,
                    input_tokens=usage_data.get("input_tokens"),
                    output_tokens=usage_data.get("output_tokens"),
                    total_tokens=usage_data.get("total_tokens"),
                )

    def explain_change(
        self,
        original: str,
        candidate: str,
        language: str,
    ) -> str:
        """Explain differences between original and candidate with caching."""
        combined_hash = compute_content_hash(f"{original}\n---MUTAGEN_SPLIT---\n{candidate}")
        operation = "explain_change"

        is_hit, cached_data = self.engine.check_exact_cache(
            content_hash=combined_hash,
            operation=operation,
            language=language,
            project_id=self.project_id,
            analysis_id=self.analysis_id,
        )
        if is_hit and cached_data and "explanation" in cached_data:
            return cached_data["explanation"]

        start_time = time.time()
        status = "success"
        error_msg = None
        explanation = ""
        request_id = generate_id()

        try:
            explanation = self._inner.explain_change(original, candidate, language)
            return explanation
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            raise
        finally:
            latency_ms = int((time.time() - start_time) * 1000)
            self.engine.record_usage(
                provider=self._inner.provider_name,
                model=self._inner.model_id,
                operation=operation,
                usage_data={"duration_ms": latency_ms},
                user_id=self.user_id,
                project_id=self.project_id,
                analysis_id=self.analysis_id,
                status=status,
                error_message=error_msg,
                request_id=request_id,
                latency_ms=latency_ms,
                estimated_prompt=original + candidate,
            )

            if status == "success" and explanation:
                self.engine.store_cache_result(
                    content_hash=combined_hash,
                    operation=operation,
                    result_json={"explanation": explanation},
                    language=language,
                    project_id=self.project_id,
                )

    def explain_failure(
        self,
        original: str,
        candidate: str,
        failure_reasons: list[str],
        language: str,
    ) -> str:
        """Explain failures with caching."""
        failures_key = ";".join(sorted(failure_reasons))
        combined_hash = compute_content_hash(f"{original}\n{candidate}\n{failures_key}")
        operation = "explain_failure"

        is_hit, cached_data = self.engine.check_exact_cache(
            content_hash=combined_hash,
            operation=operation,
            language=language,
            project_id=self.project_id,
            analysis_id=self.analysis_id,
        )
        if is_hit and cached_data and "explanation" in cached_data:
            return cached_data["explanation"]

        start_time = time.time()
        status = "success"
        error_msg = None
        result = ""
        request_id = generate_id()

        try:
            result = self._inner.explain_failure(original, candidate, failure_reasons, language)
            return result
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            raise
        finally:
            latency_ms = int((time.time() - start_time) * 1000)
            self.engine.record_usage(
                provider=self._inner.provider_name,
                model=self._inner.model_id,
                operation=operation,
                usage_data={"duration_ms": latency_ms},
                user_id=self.user_id,
                project_id=self.project_id,
                analysis_id=self.analysis_id,
                status=status,
                error_message=error_msg,
                request_id=request_id,
                latency_ms=latency_ms,
                estimated_prompt=original + candidate,
            )

            if status == "success" and result:
                self.engine.store_cache_result(
                    content_hash=combined_hash,
                    operation=operation,
                    result_json={"explanation": result},
                    language=language,
                    project_id=self.project_id,
                )

    def explain_optimization(
        self,
        original: str,
        candidate: str,
        benchmark_info: dict,
        language: str,
    ) -> str:
        """Explain verified optimizations with caching."""
        combined_hash = compute_content_hash(f"{original}\n{candidate}\n{str(benchmark_info)}")
        operation = "explain_optimization"

        is_hit, cached_data = self.engine.check_exact_cache(
            content_hash=combined_hash,
            operation=operation,
            language=language,
            project_id=self.project_id,
            analysis_id=self.analysis_id,
        )
        if is_hit and cached_data and "explanation" in cached_data:
            return cached_data["explanation"]

        start_time = time.time()
        status = "success"
        error_msg = None
        result = ""
        request_id = generate_id()

        try:
            result = self._inner.explain_optimization(original, candidate, benchmark_info, language)
            return result
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            raise
        finally:
            latency_ms = int((time.time() - start_time) * 1000)
            self.engine.record_usage(
                provider=self._inner.provider_name,
                model=self._inner.model_id,
                operation=operation,
                usage_data={"duration_ms": latency_ms},
                user_id=self.user_id,
                project_id=self.project_id,
                analysis_id=self.analysis_id,
                status=status,
                error_message=error_msg,
                request_id=request_id,
                latency_ms=latency_ms,
                estimated_prompt=original + candidate,
            )

            if status == "success" and result:
                self.engine.store_cache_result(
                    content_hash=combined_hash,
                    operation=operation,
                    result_json={"explanation": result},
                    language=language,
                    project_id=self.project_id,
                )

    def interpret_benchmark(
        self,
        benchmark_data: dict,
        baseline_data: Optional[dict] = None,
    ) -> str:
        return self._inner.interpret_benchmark(benchmark_data, baseline_data)

    def summarize_experiment(self, experiment_summary: dict) -> str:
        """Summarize experiment for evolutionary memory with tracking."""
        summary_str = json.dumps(experiment_summary, sort_keys=True, default=str)
        summary_hash = compute_content_hash(summary_str)
        operation = "summarize_experiment"

        is_hit, cached_data = self.engine.check_exact_cache(
            content_hash=summary_hash,
            operation=operation,
            project_id=self.project_id,
            analysis_id=self.analysis_id,
        )
        if is_hit and cached_data and "summary" in cached_data:
            return cached_data["summary"]

        start_time = time.time()
        status = "success"
        error_msg = None
        res = ""
        request_id = generate_id()

        try:
            res = self._inner.summarize_experiment(experiment_summary)
            return res
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            raise
        finally:
            latency_ms = int((time.time() - start_time) * 1000)
            self.engine.record_usage(
                provider=self._inner.provider_name,
                model=self._inner.model_id,
                operation=operation,
                usage_data={"duration_ms": latency_ms},
                user_id=self.user_id,
                project_id=self.project_id,
                analysis_id=self.analysis_id,
                status=status,
                error_message=error_msg,
                request_id=request_id,
                latency_ms=latency_ms,
                estimated_prompt=summary_str,
            )

            if status == "success" and res:
                self.engine.store_cache_result(
                    content_hash=summary_hash,
                    operation=operation,
                    result_json={"summary": res},
                    project_id=self.project_id,
                )

    def verify_candidate(
        self,
        prompt: str,
        system_instruction: str = "",
    ) -> str:
        """Execute candidate logical verification with usage tracking."""
        operation = "logical_verification"
        start_time = time.time()
        status = "success"
        error_msg = None
        result = ""
        request_id = generate_id()

        usage_data = {}
        try:
            if hasattr(self._inner, "verify_candidate_with_usage"):
                result, usage_data = self._inner.verify_candidate_with_usage(prompt, system_instruction)
            elif hasattr(self._inner, "verify_candidate"):
                result = self._inner.verify_candidate(prompt, system_instruction)
            elif hasattr(self._inner, "_call_with_retry"):
                result, usage_data = self._inner._call_with_retry(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    operation=operation,
                    require_json=True,
                )
            else:
                result = self._inner.explain_change(prompt, "", "python")
            return result
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            raise
        finally:
            latency_ms = int((time.time() - start_time) * 1000)
            if not usage_data:
                usage_data = {"duration_ms": latency_ms}
            elif "duration_ms" not in usage_data:
                usage_data["duration_ms"] = latency_ms

            self.engine.record_usage(
                provider=self._inner.provider_name,
                model=self._inner.model_id,
                operation=operation,
                usage_data=usage_data,
                user_id=self.user_id,
                project_id=self.project_id,
                analysis_id=self.analysis_id,
                status=status,
                error_message=error_msg,
                request_id=request_id,
                latency_ms=latency_ms,
                estimated_prompt=prompt,
                estimated_completion=result,
            )

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
