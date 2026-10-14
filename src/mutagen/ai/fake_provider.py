"""
Deterministic fake AI provider for MUTAGEN.

Used ONLY for automated tests and explicit offline demonstrations.
Never silently substituted for a real provider.
"""

from __future__ import annotations

from typing import Optional

from mutagen.ai.base import AIProviderBase
from mutagen.core.identifiers import generate_mutation_id
from mutagen.core.security import compute_content_hash
from mutagen.schemas import (
    CodeAnalysis, MemoryContext, MutationCandidate, MutationResponse,
    MutationStrategy, OptimizationObjective,
)


class FakeProvider(AIProviderBase):
    """
    Deterministic fake AI provider for testing.

    Generates predictable mutations for automated test suites.
    NEVER used silently in real experiments.
    """

    def __init__(self, model_id: str = "fake-model-v1"):
        self._model_id = model_id

    def generate_mutations(
        self,
        source_code: str,
        language: str,
        analysis: CodeAnalysis,
        objective: OptimizationObjective,
        memory_context: Optional[MemoryContext] = None,
        previous_failures: Optional[list[str]] = None,
        candidate_count: int = 4,
    ) -> MutationResponse:
        """Generate deterministic fake mutations for testing."""
        candidates = []

        strategies = [
            (MutationStrategy.CACHING, "Added memoization cache"),
            (MutationStrategy.LOOP_OPTIMIZATION, "Optimized loop iteration"),
            (MutationStrategy.REDUNDANCY_ELIMINATION, "Removed redundant computation"),
            (MutationStrategy.ALGORITHMIC, "Improved algorithm complexity"),
        ]

        for i in range(min(candidate_count, len(strategies))):
            strategy, explanation = strategies[i]

            # Generate a deterministic but syntactically valid mutation
            mutated_code = self._create_fake_mutation(source_code, i)

            candidate = MutationCandidate(
                candidate_id=generate_mutation_id(),
                source_code=mutated_code,
                strategy=strategy,
                explanation=f"[FAKE] {explanation}",
                expected_improvement=f"~{(i + 1) * 5}% improvement (fake estimate)",
                potential_risks="None (deterministic test mutation)",
                assumptions="Test environment only",
                content_hash=compute_content_hash(mutated_code),
            )
            candidates.append(candidate)

        return MutationResponse(
            candidates=candidates,
            model_id=self._model_id,
            usage={"input_tokens": 100, "output_tokens": 200, "total_tokens": 300},
        )

    def explain_change(
        self,
        original: str,
        candidate: str,
        language: str,
    ) -> str:
        """Return a deterministic explanation."""
        return (
            f"[FAKE EXPLANATION] The candidate modifies the original {language} code. "
            f"Original: {len(original)} chars, Candidate: {len(candidate)} chars. "
            f"This is a deterministic test explanation."
        )

    def analyze_code(
        self,
        source_code: str,
        language: str,
        objective: OptimizationObjective = OptimizationObjective.BALANCED,
        static_context: Optional[dict] = None,
    ) -> dict:
        """Deterministic fake analysis."""
        return {
            "language": language,
            "structural_summary": {
                "functions": ["fake_target"],
                "classes": [],
                "public_interface": ["fake_target"],
                "external_dependencies": [],
            },
            "complexity": {
                "estimated_time_complexity": "O(n)",
                "estimated_space_complexity": "O(1)",
                "bottlenecks": ["Nested loop in fake test target"],
            },
            "optimization_suggestions": [
                {
                    "target_symbol": "fake_target",
                    "strategy": "algorithmic",
                    "description": "Replace iteration with vectorized computation",
                    "expected_impact": "speed improvement",
                }
            ],
            "correctness_invariants": [
                "Return type and public contract must remain identical"
            ],
            "usage": {
                "input_tokens": 120,
                "output_tokens": 155,
                "total_tokens": 275,
                "duration_ms": 15,
            },
        }

    def explain_failure(
        self,
        original: str,
        candidate: str,
        failure_reasons: list[str],
        language: str,
    ) -> str:
        """Return a deterministic failure explanation."""
        reasons = "; ".join(failure_reasons) if failure_reasons else "None"
        return f"[FAKE FAILURE] Candidate failed in {language}. Reasons: {reasons}"

    def explain_optimization(
        self,
        original: str,
        candidate: str,
        benchmark_info: dict,
        language: str,
    ) -> str:
        """Return a deterministic optimization explanation."""
        return (
            f"[FAKE OPTIMIZATION] Optimized {language} code. "
            f"Median runtime: {benchmark_info.get('median_time', 0.001)}s."
        )

    def interpret_benchmark(
        self,
        benchmark_data: dict,
        baseline_data: Optional[dict] = None,
    ) -> str:
        """Return a deterministic benchmark interpretation."""
        return f"[FAKE BENCHMARK] Median runtime: {benchmark_data.get('median_time', 0.001)}s."

    def summarize_experiment(self, experiment_summary: dict) -> str:
        """Return a deterministic experiment summary."""
        return (
            f"[FAKE SUMMARY] Experiment completed with "
            f"{experiment_summary.get('total_candidates', 0)} candidates tested. "
            f"This is a deterministic test summary."
        )

    def check_availability(self) -> tuple[bool, str]:
        """Fake provider is always available."""
        return True, f"Fake provider ({self._model_id}) is available (test mode)"

    def verify_candidate(
        self,
        prompt: str,
        system_instruction: str = "",
    ) -> str:
        """Return structured verification response for tests."""
        return json.dumps({
            "verdict": "PASS",
            "confidence": 0.95,
            "logical_correctness": {"status": "PASS", "reason": "All logical invariants verified."},
            "behavior_preservation": {"status": "PASS", "reason": "Deterministic behavior preserved."},
            "edge_cases": [
                {"case": "empty input", "risk": "LOW", "reason": "Handled gracefully"}
            ],
            "detected_errors": [],
            "suggested_tests": ["test_boundary()"],
            "recommendation": "ACCEPT",
        })

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_id(self) -> str:
        return self._model_id

    def _create_fake_mutation(self, source_code: str, variant: int) -> str:
        """
        Create a deterministic mutation by adding a comment and minor changes.

        The result is syntactically valid Python that preserves the public interface.
        """
        lines = source_code.splitlines()
        comment = f"# MUTAGEN fake mutation variant {variant}"

        # Insert a comment near the top
        if lines:
            # Find the first non-comment, non-blank, non-import line
            insert_at = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and not stripped.startswith("import") \
                        and not stripped.startswith("from") and not stripped.startswith('"""') \
                        and not stripped.startswith("'''"):
                    insert_at = i
                    break

            lines.insert(insert_at, comment)

        return "\n".join(lines)
