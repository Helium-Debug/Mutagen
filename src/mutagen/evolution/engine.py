"""
Multi-generation evolution engine for MUTAGEN.

Orchestrates the full evolutionary optimization loop:
analyze → retrieve memory → mutate → validate → test → benchmark → evaluate → select → persist.
"""

from __future__ import annotations

import time
from typing import Optional

from mutagen.ai.base import AIProviderBase
from mutagen.analysis.python_analyzer import PythonAnalyzer
from mutagen.benchmarking import BenchmarkRunner, compare_benchmarks
from mutagen.config import get_settings
from mutagen.core.identifiers import generate_experiment_id, generate_id, utc_now
from mutagen.core.logging import get_logger, set_correlation_id
from mutagen.core.security import compute_content_hash
from mutagen.db.repositories import (
    CandidateRepository, ExperimentRepository, GenerationRepository,
    AuditRepository, SourceDiffRepository,
)
from mutagen.db.session import get_session
from mutagen.evolution.fitness import FitnessEvaluator, calculate_improvement
from mutagen.exceptions import MutagenExperimentError, MutagenCancellationError
from mutagen.memory import MemoryManager
from mutagen.sandbox.docker_manager import DockerSandbox
from mutagen.services.diff_service import DiffService
from mutagen.schemas import (
    CandidateStatus, CodeAnalysis, ExperimentConfig, ExperimentStatus,
    ExperimentSummary, FitnessScore, MutationCandidate, OptimizationObjective,
    ValidationResult,
)
from mutagen.testing.test_runner import TestRunner
from mutagen.verification import VerificationPipeline, VerificationVerdict

logger = get_logger("evolution.engine")


class EvolutionEngine:
    """
    Multi-generation evolution engine.

    Runs the complete evolutionary optimization loop with:
    - Configurable generation count and population size
    - Elitism (best candidate preserved)
    - Stagnation detection
    - Content hash deduplication
    - Memory-informed mutation generation
    """

    def __init__(
        self,
        ai_provider: AIProviderBase,
        config: ExperimentConfig,
        progress_callback: Optional[callable] = None,
    ):
        self.ai = ai_provider
        self.config = config
        self.progress = progress_callback or (lambda stage, msg: None)
        self.settings = get_settings()
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the running experiment."""
        self._cancelled = True

    def run(self) -> ExperimentSummary:
        """
        Execute the full evolution experiment.

        Returns:
            ExperimentSummary with the final results.
        """
        experiment_id = generate_experiment_id()
        set_correlation_id(experiment_id)
        start_time = time.time()

        self.progress("init", f"Starting experiment {experiment_id}")
        logger.info(f"Starting evolution experiment {experiment_id}")

        # Read and analyze source code
        source_code = self._read_source()
        source_hash = compute_content_hash(source_code)

        self.progress("analyzing", "Analyzing source code")
        analysis = self._analyze_source(source_code)

        if not analysis.syntax_valid:
            raise MutagenExperimentError(
                f"Source code has syntax errors: {'; '.join(analysis.syntax_errors)}"
            )

        with get_session() as session:
            # Ensure AI provider is tracked and token-optimized with active session
            from mutagen.ai.tracker import TrackedAIProvider
            if not isinstance(self.ai, TrackedAIProvider):
                self.ai = TrackedAIProvider(
                    self.ai,
                    user_id=self.config.user_id,
                    project_id=self.config.project_id,
                    analysis_id=experiment_id,
                    session=session,
                )
            else:
                self.ai.analysis_id = experiment_id
                self.ai.project_id = self.config.project_id
                self.ai.user_id = self.config.user_id
                self.ai.set_session(session)

            exp_repo = ExperimentRepository(session)
            gen_repo = GenerationRepository(session)
            cand_repo = CandidateRepository(session)
            audit_repo = AuditRepository(session)
            memory_mgr = MemoryManager(session, user_id=self.config.user_id)

            # Create experiment record
            experiment = exp_repo.create(
                id=experiment_id,
                user_id=self.config.user_id,
                project_id=self.config.project_id,
                source_file=self.config.source_file,
                source_hash=source_hash,
                source_content=source_code,
                language=self.config.language.value,
                objective=self.config.objective.value,
                status=ExperimentStatus.RUNNING.value,
                generations_total=self.config.generations,
                population_size=self.config.population_size,
                benchmark_repetitions=self.config.benchmark_repetitions,
                execution_timeout=self.config.execution_timeout,
                memory_limit_mb=self.config.memory_limit_mb,
                fitness_weights=self.config.fitness_weights,
                config_json=self.config.model_dump(),
            )

            audit_repo.log_event(
                "experiment_started",
                entity_type="experiment",
                entity_id=experiment_id,
                correlation_id=experiment_id,
                user_id=self.config.user_id,
            )
            session.commit()

            # Setup sandbox and runners
            sandbox = DockerSandbox()
            test_runner = TestRunner(sandbox, timeout=self.config.execution_timeout)
            bench_runner = BenchmarkRunner(
                sandbox,
                repetitions=self.config.benchmark_repetitions,
                timeout=self.config.execution_timeout,
            )
            fitness_eval = FitnessEvaluator(
                objective=self.config.objective,
                custom_weights=self.config.fitness_weights,
            )
            verification_pipeline = VerificationPipeline(
                sandbox=sandbox,
                ai_provider=self.ai,
                test_runner=test_runner,
                timeout=self.config.execution_timeout,
            )

            # Baseline tests and benchmark
            baseline_test_result = None
            try:
                baseline_test_result = test_runner.run_tests(
                    candidate_id="baseline",
                    code=source_code,
                    test_command=self.config.test_command,
                )
            except Exception as e:
                logger.debug(f"Baseline test execution: {e}")

            self.progress("benchmarking", "Benchmarking baseline implementation")
            baseline_benchmark = None
            try:
                baseline_benchmark = bench_runner.benchmark(
                    candidate_id="baseline",
                    code=source_code,
                )
            except Exception as e:
                logger.warning(f"Baseline benchmark failed: {e}")

            # Track best across generations
            global_best_score: Optional[FitnessScore] = None
            global_best_candidate: Optional[MutationCandidate] = None
            global_best_candidate_id: Optional[str] = None
            gen_num: int = 0
            stagnation_count = 0
            stagnation_threshold = max(2, self.config.generations // 3)
            previous_failures: list[str] = []
            seen_hashes: set[str] = {source_hash}

            # ── Generation Loop ──────────────────────────────
            for gen_num in range(1, self.config.generations + 1):
                if self._cancelled:
                    exp_repo.update_status(experiment_id, ExperimentStatus.CANCELLED.value)
                    raise MutagenCancellationError("Experiment cancelled by user")

                if gen_num > 1 and getattr(self.ai, "provider_name", "") != "gemma":
                    self.progress("cooling", "Pacing between generations for API token rate limits (18s)...")
                    time.sleep(18)

                gen_start = time.time()
                self.progress("generation", f"Generation {gen_num}/{self.config.generations}")
                logger.info(f"Starting generation {gen_num}")

                # 1. Retrieve memory
                self.progress("memory", "Retrieving evolutionary memory")
                memory_context = memory_mgr.retrieve_context(
                    language=self.config.language.value,
                )

                # 2. Generate mutations
                self.progress("mutating", f"Generating {self.config.population_size} mutations")
                try:
                    mutation_response = self.ai.generate_mutations(
                        source_code=source_code,
                        language=self.config.language.value,
                        analysis=analysis,
                        objective=self.config.objective,
                        memory_context=memory_context,
                        previous_failures=previous_failures[-5:],
                        candidate_count=self.config.population_size,
                    )
                except Exception as e:
                    logger.error(f"Mutation generation failed in gen {gen_num}: {e}")
                    try:
                        session.rollback()
                    except Exception:
                        pass
                    err_msg = str(e)
                    if "Error code:" in err_msg:
                        err_msg = err_msg.split("Error code:")[0].strip() or "API rate limit encountered"
                    previous_failures.append(f"Generation {gen_num}: {err_msg[:120]}")
                    continue

                candidates = mutation_response.candidates
                gen_candidates_valid = 0
                gen_candidates_tested = 0
                gen_fitness_scores: list[FitnessScore] = []

                # 3. Process each candidate
                for candidate in candidates:
                    if self._cancelled:
                        break

                    # Deduplication
                    if candidate.content_hash in seen_hashes:
                        logger.info(f"Duplicate candidate {candidate.candidate_id} — skipping")
                        continue
                    seen_hashes.add(candidate.content_hash)

                    # Store candidate in DB
                    db_cand = cand_repo.create(
                        id=candidate.candidate_id,
                        experiment_id=experiment_id,
                        generation_number=gen_num,
                        source_code=candidate.source_code,
                        content_hash=candidate.content_hash,
                        strategy=candidate.strategy.value,
                        explanation=candidate.explanation,
                        expected_improvement=candidate.expected_improvement,
                        potential_risks=candidate.potential_risks,
                        status=CandidateStatus.VALIDATING.value,
                    )
                    candidate.candidate_id = db_cand.id

                    # Persist programmatic diff and change metrics
                    try:
                        diff_repo = SourceDiffRepository(session)
                        cand_diff = DiffService.compute_unified_diff(
                            original=source_code,
                            candidate=candidate.source_code,
                            fromfile=f"a/{self.config.source_file}",
                            tofile=f"b/{self.config.source_file}",
                        )
                        cand_summary = DiffService.summarize_changes(
                            original=source_code,
                            candidate=candidate.source_code,
                            file_path=self.config.source_file,
                        )
                        diff_repo.create(
                            experiment_id=experiment_id,
                            candidate_id=candidate.candidate_id,
                            file_path=self.config.source_file,
                            diff_text=cand_diff,
                            files_changed=cand_summary.files_changed,
                            lines_added=cand_summary.lines_added,
                            lines_removed=cand_summary.lines_removed,
                            functions_modified=cand_summary.functions_modified,
                            summary_json=cand_summary.model_dump(),
                        )
                    except Exception as e:
                        logger.warning(f"Could not persist source diff for candidate {candidate.candidate_id}: {e}")
                        try:
                            session.rollback()
                        except Exception:
                            pass
                    try:
                        session.commit()
                    except Exception:
                        pass

                    # 4. Syntactic & Contract Validation
                    self.progress("validating", f"Validating candidate {candidate.candidate_id[:12]}")
                    validation = self._validate_candidate(candidate, analysis)

                    if not validation.is_valid:
                        cand_repo.update_status(
                            candidate.candidate_id,
                            CandidateStatus.REJECTED.value,
                            validation_errors={"errors": validation.errors},
                            verification_passed=False,
                            verification_verdict="REJECT",
                        )
                        try:
                            session.commit()
                        except Exception:
                            pass
                        short_errs = [err[:80] for err in validation.errors[:3]]
                        previous_failures.append(
                            f"Candidate rejected: {'; '.join(short_errs)}"
                        )
                        continue

                    # 5. Semantic & Logical Verification Layer
                    candidate_analysis = self._analyze_source(candidate.source_code)
                    cand_diff_text = cand_diff if 'cand_diff' in locals() and cand_diff else ""

                    self.progress("verifying", f"Verifying candidate {candidate.candidate_id[:12]} correctness")
                    verification_report = verification_pipeline.verify(
                        candidate=candidate,
                        original_code=source_code,
                        original_analysis=analysis,
                        candidate_analysis=candidate_analysis,
                        diff_text=cand_diff_text,
                        test_command=self.config.test_command,
                        original_test_result=baseline_test_result,
                        progress_callback=self.progress,
                    )

                    if verification_report.final_verdict == VerificationVerdict.REJECT:
                        # Attempt automated repair using locally available Gemma 2
                        self.progress("repairing", f"Candidate {candidate.candidate_id[:12]} failed verification; attempting repair with local gemma2...")
                        try:
                            from mutagen.ai.repair import CodeRepairService
                            repair_svc = CodeRepairService()
                            rep_res = repair_svc.repair_code(
                                code=candidate.source_code,
                                failures=verification_report.rejection_reasons,
                                language=self.config.language.value,
                            )
                            if rep_res.success and rep_res.changes_made:
                                self.progress("repaired", f"Candidate repaired via {rep_res.model_used}. Re-verifying...")
                                candidate.source_code = rep_res.repaired_code
                                candidate_analysis = self._analyze_source(candidate.source_code)
                                verification_report = verification_pipeline.verify(
                                    candidate=candidate,
                                    original_code=source_code,
                                    original_analysis=analysis,
                                    candidate_analysis=candidate_analysis,
                                    diff_text=cand_diff_text,
                                    test_command=self.config.test_command,
                                    original_test_result=baseline_test_result,
                                    progress_callback=self.progress,
                                )
                        except Exception as e:
                            logger.debug(f"Auto-repair attempt failed: {e}")

                    if verification_report.final_verdict == VerificationVerdict.REJECT:
                        cand_repo.update_status(
                            candidate.candidate_id,
                            CandidateStatus.REJECTED.value,
                            validation_errors={"errors": verification_report.rejection_reasons},
                            verification_passed=False,
                            verification_verdict="REJECT",
                            verification_json=verification_report.model_dump(),
                        )
                        try:
                            session.commit()
                        except Exception:
                            pass
                        short_errs = [err[:80] for err in verification_report.rejection_reasons[:3]]
                        previous_failures.append(
                            f"Verification rejected: {'; '.join(short_errs)}"
                        )
                        self.progress(
                            "rejected",
                            f"✗ Candidate {candidate.candidate_id[:12]} rejected by verification: {short_errs[0] if short_errs else 'Correctness failed'}"
                        )
                        continue

                    gen_candidates_valid += 1
                    cand_repo.update_status(
                        candidate.candidate_id,
                        CandidateStatus.VALID.value,
                        validation_passed=True,
                        verification_passed=(verification_report.final_verdict == VerificationVerdict.ACCEPT),
                        verification_verdict=verification_report.final_verdict.value,
                        verification_json=verification_report.model_dump(),
                    )
                    try:
                        session.commit()
                    except Exception:
                        pass
                    self.progress(
                        "verified",
                        f"✓ Candidate {candidate.candidate_id[:12]} verified ({verification_report.final_verdict.value}) "
                        f"[Logic confidence: {int(verification_report.logic.confidence * 100)}%]"
                    )

                    # 6. Benchmark (only for verified candidates)
                    benchmark_result = None
                    self.progress(
                        "benchmarking",
                        f"Benchmarking candidate {candidate.candidate_id[:12]}"
                    )
                    try:
                        benchmark_result = bench_runner.benchmark(
                            candidate_id=candidate.candidate_id,
                            code=candidate.source_code,
                        )
                        cand_repo.update_status(
                            candidate.candidate_id,
                            CandidateStatus.BENCHMARKED.value,
                            benchmark_results_json=benchmark_result.model_dump(),
                            median_time=benchmark_result.median_time,
                        )
                    except Exception as e:
                        logger.warning(f"Benchmark failed for {candidate.candidate_id}: {e}")

                    gen_candidates_tested += 1

                    # 7. Evaluate fitness (incorporating verification report)
                    fitness = fitness_eval.evaluate(
                        candidate_id=candidate.candidate_id,
                        validation=validation,
                        test_result=None,
                        benchmark=benchmark_result,
                        baseline_benchmark=baseline_benchmark,
                        candidate_analysis=candidate_analysis,
                        original_analysis=analysis,
                        verification_report=verification_report,
                    )
                    gen_fitness_scores.append(fitness)

                    cand_repo.update_status(
                        candidate.candidate_id,
                        CandidateStatus.BENCHMARKED.value if benchmark_result else CandidateStatus.VALID.value,
                        fitness_score=fitness.overall_score,
                        fitness_components=fitness.model_dump(),
                        speed_improvement=fitness.speed_improvement_percent,
                        memory_improvement=fitness.memory_improvement_percent,
                        is_eligible=fitness.is_eligible,
                    )
                    try:
                        session.commit()
                    except Exception:
                        pass

                # 8. Select best from this generation
                ranked = fitness_eval.rank_candidates(gen_fitness_scores)
                gen_best = ranked[0] if ranked and ranked[0].is_eligible else None

                if gen_best:
                    if (global_best_score is None or
                            gen_best.overall_score > global_best_score.overall_score):
                        global_best_score = gen_best
                        global_best_candidate_id = gen_best.candidate_id
                        stagnation_count = 0
                        logger.info(
                            f"New best candidate: {gen_best.candidate_id} "
                            f"(score={gen_best.overall_score:.4f})"
                        )
                    else:
                        stagnation_count += 1
                else:
                    stagnation_count += 1

                # Save generation record
                gen_repo.create(
                    experiment_id=experiment_id,
                    generation_number=gen_num,
                    candidates_generated=len(candidates),
                    candidates_valid=gen_candidates_valid,
                    candidates_tested=gen_candidates_tested,
                    best_fitness=gen_best.overall_score if gen_best else None,
                    best_candidate_id=gen_best.candidate_id if gen_best else None,
                    duration_seconds=time.time() - gen_start,
                )

                exp_repo.update_status(
                    experiment_id,
                    ExperimentStatus.RUNNING.value,
                    generations_completed=gen_num,
                )
                try:
                    session.commit()
                except Exception:
                    pass

                # Stagnation check
                if stagnation_count >= stagnation_threshold:
                    if getattr(self.config, "stop_on_stagnation", False):
                        logger.info(
                            f"Stopping: no improvement for {stagnation_count} generations"
                        )
                        self.progress("stagnation", f"Stopping due to stagnation ({stagnation_count} generations without improvement)")
                        break
                    else:
                        if gen_num < self.config.generations:
                            logger.info(
                                f"Stagnation detected ({stagnation_count} gen) — carrying on with next evolution generation"
                            )
                            self.progress(
                                "stagnation",
                                f"Stagnation detected ({stagnation_count} gen without improvement) — carrying on with next evolution ({gen_num + 1}/{self.config.generations})..."
                            )
                            previous_failures.append(
                                f"Generation {gen_num}: Stagnation detected. Try a different optimization strategy (e.g., caching, loop optimization, algorithmic change)."
                            )
                        else:
                            self.progress("stagnation", "Stagnation reached at final generation — showing results")

                self.progress(
                    "generation_complete",
                    f"Generation {gen_num} complete: "
                    f"{gen_candidates_valid} valid, {gen_candidates_tested} tested"
                )

            # ── Finalize ─────────────────────────────────────
            duration = time.time() - start_time

            # Count candidates
            all_candidates = cand_repo.list_for_experiment(experiment_id)
            total_candidates = len(all_candidates)
            valid_candidates = sum(1 for c in all_candidates if c.is_eligible)

            best_improvement = None
            best_cand_id = None

            # Determine final status
            if self._cancelled:
                final_status = ExperimentStatus.CANCELLED
            elif global_best_score and global_best_score.is_eligible:
                final_status = ExperimentStatus.SUCCEEDED
                best_cand_id = global_best_score.candidate_id
                best_improvement = global_best_score.speed_improvement_percent

                # Mark best candidate
                cand_repo.update_status(
                    global_best_score.candidate_id,
                    CandidateStatus.BEST_ELIGIBLE.value,
                )
            else:
                # If stopped for stagnation or no candidate beat baseline,
                # do not show as fail! Preserve evaluated candidates and show results.
                eligible_cands = [c for c in all_candidates if c.is_eligible]
                tested_cands = [
                    c for c in all_candidates
                    if c.status in (CandidateStatus.BENCHMARKED.value, CandidateStatus.VALID.value, CandidateStatus.TESTED.value)
                ]
                target_cand = eligible_cands[0] if eligible_cands else (tested_cands[0] if tested_cands else (all_candidates[0] if all_candidates else None))

                if target_cand:
                    final_status = ExperimentStatus.SUCCEEDED
                    best_cand_id = target_cand.id
                    best_improvement = target_cand.speed_improvement or 0.0
                    cand_repo.update_status(
                        target_cand.id,
                        CandidateStatus.BEST_ELIGIBLE.value,
                    )
                elif total_candidates > 0:
                    final_status = ExperimentStatus.SUCCEEDED
                else:
                    final_status = ExperimentStatus.FAILED

            exp_repo.update_status(
                experiment_id,
                final_status.value,
                best_candidate_id=best_cand_id,
                best_improvement_percent=best_improvement,
                total_candidates=total_candidates,
                valid_candidates=valid_candidates,
                duration_seconds=duration,
            )

            # 9. Update memory
            self.progress("memory_update", "Updating evolutionary memory")
            strategies_tried = list({c.strategy for c in all_candidates})
            failures = [
                c.explanation or "Unknown failure"
                for c in all_candidates
                if not c.is_eligible
            ][:5]

            try:
                memory_mgr.store_experiment_outcome(
                    experiment_id=experiment_id,
                    project_id=None,
                    language=self.config.language.value,
                    summary=f"{'Successful' if final_status == ExperimentStatus.SUCCEEDED else 'Failed'} "
                            f"optimization experiment with {total_candidates} candidates",
                    strategies_tried=strategies_tried,
                    best_improvement=best_improvement,
                    failures=failures,
                )
            except Exception as e:
                logger.warning(f"Failed to update memory: {e}")
                try:
                    session.rollback()
                except Exception:
                    pass

            audit_repo.log_event(
                "experiment_completed",
                entity_type="experiment",
                entity_id=experiment_id,
                details={
                    "status": final_status.value,
                    "candidates": total_candidates,
                    "best_improvement": best_improvement,
                    "duration": duration,
                },
                correlation_id=experiment_id,
            )

            self.progress("complete", f"Experiment {experiment_id} complete: {final_status.value}")

            return ExperimentSummary(
                experiment_id=experiment_id,
                status=final_status,
                source_file=self.config.source_file,
                language=self.config.language,
                objective=self.config.objective,
                generations_completed=gen_num if 'gen_num' in dir() else 0,
                generations_total=self.config.generations,
                total_candidates=total_candidates,
                valid_candidates=valid_candidates,
                best_candidate_id=best_cand_id,
                best_improvement_percent=best_improvement,
                duration_seconds=duration,
            )

    def _read_source(self) -> str:
        """Read and validate the source file."""
        from pathlib import Path
        from mutagen.core.security import validate_source_content

        path = Path(self.config.source_file)
        if not path.exists():
            raise MutagenExperimentError(f"Source file not found: {path}")
        if not path.is_file():
            raise MutagenExperimentError(f"Not a file: {path}")

        content = path.read_text(encoding="utf-8")
        validate_source_content(content, max_size=self.settings.max_source_size)
        return content

    def _analyze_source(self, source: str) -> CodeAnalysis:
        """Analyze the source code."""
        analyzer = PythonAnalyzer()
        return analyzer.analyze(source, file_path=self.config.source_file)

    def _validate_candidate(
        self,
        candidate: MutationCandidate,
        original_analysis: CodeAnalysis,
    ) -> ValidationResult:
        """
        Validate a mutation candidate.

        Checks syntax, size, interface preservation, and security.
        """
        result = ValidationResult(candidate_id=candidate.candidate_id)
        errors = []

        # 1. Source size check
        source_bytes = len(candidate.source_code.encode("utf-8"))
        if source_bytes > self.settings.max_source_size:
            errors.append(f"Candidate source too large: {source_bytes} bytes")
        else:
            result.size_valid = True

        # 2. Syntax check
        analyzer = PythonAnalyzer()
        syntax_valid, syntax_errors = analyzer.validate_syntax(candidate.source_code)
        result.syntax_valid = syntax_valid
        if not syntax_valid:
            errors.extend(syntax_errors)

        # 3. Interface preservation check
        if syntax_valid:
            candidate_interface = set(analyzer.extract_public_interface(candidate.source_code))
            original_interface = set(original_analysis.public_interface)

            missing = original_interface - candidate_interface
            if missing:
                errors.append(
                    f"Public interface not preserved. Missing: {', '.join(missing)}"
                )
            else:
                result.interface_preserved = True

        # 4. Security checks
        result.security_check_passed = self._security_check(candidate.source_code)
        if not result.security_check_passed:
            errors.append("Security check failed: suspicious patterns detected")

        result.errors = errors
        result.is_valid = (
            result.size_valid and
            result.syntax_valid and
            result.interface_preserved and
            result.security_check_passed and
            len(errors) == 0
        )

        return result

    def _security_check(self, source: str) -> bool:
        """
        Basic security checks on candidate source code.

        Note: This is NOT a complete security boundary. All untrusted code
        runs in the Docker sandbox regardless.
        """
        import re

        suspicious_patterns = [
            r"os\.system\s*\(",
            r"subprocess\.(run|call|Popen|check_output)\s*\(",
            r"__import__\s*\(",
            r"eval\s*\(",
            r"exec\s*\(",
            r"(?<!re\.)(?<!\.)\bcompile\s*\(",
            r"open\s*\([^)]*['\"]\/etc",
            r"socket\.",
            r"requests\.(get|post|put|delete)\s*\(",
            r"urllib\.request",
        ]

        for pattern in suspicious_patterns:
            if re.search(pattern, source):
                logger.warning(f"Suspicious pattern in candidate: {pattern}")
                return False

        return True
