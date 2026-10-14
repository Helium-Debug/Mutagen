"""
Multi-objective fitness evaluation engine for MUTAGEN.

Evaluates candidates across correctness, speed, memory, complexity,
and maintainability using configurable weights.

Correctness is a mandatory acceptance condition — failing tests
means the candidate is ineligible regardless of other scores.
"""

from __future__ import annotations

from typing import Optional

from mutagen.schemas import (
    BenchmarkResult, CodeAnalysis, FitnessScore, OptimizationObjective,
    TestResult, ValidationResult,
)


# Default fitness weights by objective
DEFAULT_WEIGHTS = {
    OptimizationObjective.SPEED: {
        "speed": 0.60, "memory": 0.15, "complexity": 0.15, "maintainability": 0.10
    },
    OptimizationObjective.MEMORY: {
        "speed": 0.15, "memory": 0.60, "complexity": 0.15, "maintainability": 0.10
    },
    OptimizationObjective.BALANCED: {
        "speed": 0.35, "memory": 0.25, "complexity": 0.20, "maintainability": 0.20
    },
}


class FitnessEvaluator:
    """
    Multi-objective fitness evaluator.

    Correctness is binary — failing mandatory tests means ineligible.
    Other dimensions are scored and combined using normalized weights.
    """

    def __init__(
        self,
        objective: OptimizationObjective = OptimizationObjective.BALANCED,
        custom_weights: Optional[dict[str, float]] = None,
    ):
        self.objective = objective
        self.weights = custom_weights or DEFAULT_WEIGHTS.get(
            objective, DEFAULT_WEIGHTS[OptimizationObjective.BALANCED]
        )
        self._validate_weights()

    def evaluate(
        self,
        candidate_id: str,
        validation: ValidationResult,
        test_result: Optional[TestResult],
        benchmark: Optional[BenchmarkResult],
        baseline_benchmark: Optional[BenchmarkResult],
        candidate_analysis: Optional[CodeAnalysis] = None,
        original_analysis: Optional[CodeAnalysis] = None,
        verification_report: Optional[Any] = None,
    ) -> FitnessScore:
        """
        Evaluate a candidate's fitness across all objectives.

        Args:
            candidate_id: The candidate's ID.
            validation: Validation results.
            test_result: Test execution results.
            benchmark: Candidate's benchmark results.
            baseline_benchmark: Original code benchmark results.
            candidate_analysis: Code analysis of the candidate.
            original_analysis: Code analysis of the original.
            verification_report: Verification layer results.

        Returns:
            FitnessScore with all components.
        """
        score = FitnessScore(
            candidate_id=candidate_id,
            weights=self.weights,
        )

        # ── Mandatory: Verification Layer ──────────────────
        if verification_report is not None:
            verdict_val = (
                verification_report.final_verdict.value
                if hasattr(verification_report.final_verdict, "value")
                else str(verification_report.final_verdict)
            )
            if verdict_val == "REJECT":
                score.correctness_score = 0.0
                score.is_eligible = False
                for reason in getattr(verification_report, "rejection_reasons", []):
                    score.rejection_reasons.append(f"Verification rejected: {reason}")
                return score
            elif verdict_val == "ACCEPT":
                score.correctness_score = 1.0
            elif verdict_val == "REVIEW":
                score.correctness_score = 0.95

        # ── Mandatory: Validation ──────────────────────────
        if not validation.is_valid:
            score.rejection_reasons.append(
                f"Validation failed: {'; '.join(validation.errors)}"
            )
            return score

        # ── Mandatory: Correctness ─────────────────────────
        if test_result:
            if test_result.all_passed:
                score.correctness_score = max(score.correctness_score, 1.0)
            else:
                score.correctness_score = 0.0
                reasons = []
                if test_result.failed > 0:
                    reasons.append(f"{test_result.failed} test(s) failed")
                if test_result.errors > 0:
                    reasons.append(f"{test_result.errors} error(s)")
                if test_result.timed_out:
                    reasons.append("execution timed out")
                score.rejection_reasons.append(
                    f"Correctness check failed: {'; '.join(reasons)}"
                )
                return score
        elif verification_report is None:
            # No test results and no verification report — candidate cannot be verified
            score.correctness_score = 0.5
            score.rejection_reasons.append(
                "No test results available — correctness unverified"
            )

        # ── Speed Score ────────────────────────────────────
        if benchmark and baseline_benchmark:
            if baseline_benchmark.median_time > 0:
                improvement = (
                    (baseline_benchmark.median_time - benchmark.median_time)
                    / baseline_benchmark.median_time
                ) * 100
                score.speed_improvement_percent = improvement
                # Normalize: 0% improvement = 0.5, 100% = 1.0, -100% = 0.0
                score.speed_score = max(0.0, min(1.0, 0.5 + improvement / 200))
            else:
                score.speed_score = 0.5
        else:
            score.speed_score = 0.5

        # ── Memory Score ───────────────────────────────────
        if (benchmark and baseline_benchmark and
                benchmark.median_memory is not None and
                baseline_benchmark.median_memory is not None and
                baseline_benchmark.median_memory > 0):
            mem_improvement = (
                (baseline_benchmark.median_memory - benchmark.median_memory)
                / baseline_benchmark.median_memory
            ) * 100
            score.memory_improvement_percent = mem_improvement
            score.memory_score = max(0.0, min(1.0, 0.5 + mem_improvement / 200))
        else:
            score.memory_score = 0.5

        # ── Complexity Score ───────────────────────────────
        if candidate_analysis and original_analysis:
            if original_analysis.complexity_score > 0:
                complexity_ratio = (
                    candidate_analysis.complexity_score / original_analysis.complexity_score
                )
                # Lower complexity = better score
                score.complexity_score = max(0.0, min(1.0, 1.0 - (complexity_ratio - 1.0) * 0.5))
            else:
                score.complexity_score = 0.5
        else:
            score.complexity_score = 0.5

        # ── Maintainability Score ──────────────────────────
        if candidate_analysis and original_analysis:
            # Heuristic: similar line count is better, fewer lines is slightly better
            if original_analysis.lines_code > 0:
                line_ratio = candidate_analysis.lines_code / original_analysis.lines_code
                if line_ratio <= 1.0:
                    score.maintainability_score = 0.5 + (1.0 - line_ratio) * 0.3
                else:
                    score.maintainability_score = max(0.0, 0.5 - (line_ratio - 1.0) * 0.3)
            else:
                score.maintainability_score = 0.5
        else:
            score.maintainability_score = 0.5

        # ── Overall Score (weighted) ───────────────────────
        score.overall_score = (
            self.weights.get("speed", 0.0) * score.speed_score +
            self.weights.get("memory", 0.0) * score.memory_score +
            self.weights.get("complexity", 0.0) * score.complexity_score +
            self.weights.get("maintainability", 0.0) * score.maintainability_score
        )

        # Eligibility: must pass correctness (ACCEPT or REVIEW)
        score.is_eligible = score.correctness_score >= 0.85 and len(score.rejection_reasons) == 0

        return score

    def rank_candidates(self, scores: list[FitnessScore]) -> list[FitnessScore]:
        """
        Rank candidates by overall fitness score.

        Eligible candidates always rank above ineligible ones.
        """
        eligible = [s for s in scores if s.is_eligible]
        ineligible = [s for s in scores if not s.is_eligible]

        eligible.sort(key=lambda s: s.overall_score, reverse=True)
        ineligible.sort(key=lambda s: s.overall_score, reverse=True)

        return eligible + ineligible

    def tournament_select(
        self,
        scores: list[FitnessScore],
        tournament_size: int = 3,
        count: int = 2,
    ) -> list[FitnessScore]:
        """
        Tournament selection: pick the best from random subsets.

        Only eligible candidates participate.
        """
        import random

        eligible = [s for s in scores if s.is_eligible]
        if not eligible:
            return []

        selected = []
        for _ in range(min(count, len(eligible))):
            tournament = random.sample(eligible, min(tournament_size, len(eligible)))
            winner = max(tournament, key=lambda s: s.overall_score)
            selected.append(winner)

        return selected


    def _validate_weights(self) -> None:
        """Validate that weights are normalized."""
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            # Auto-normalize
            if total > 0:
                self.weights = {k: v / total for k, v in self.weights.items()}


def tournament_selection(
    scores: list[FitnessScore],
    tournament_size: int = 3,
) -> Optional[FitnessScore]:
    """Convenience function for single tournament selection winner."""
    evaluator = FitnessEvaluator()
    winners = evaluator.tournament_select(scores, tournament_size=tournament_size, count=1)
    return winners[0] if winners else None


def calculate_improvement(baseline: float, candidate: float) -> float:
    """
    Calculate improvement percentage.

    A positive value means the candidate uses less of the resource.
    A negative value means the candidate uses more (regression).

    Handles zero baselines safely.
    """
    if baseline <= 0:
        return 0.0
    return ((baseline - candidate) / baseline) * 100
