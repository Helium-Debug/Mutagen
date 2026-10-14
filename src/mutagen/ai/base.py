"""
Abstract base class for AI providers in MUTAGEN.

All AI providers must implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from mutagen.schemas import (
    CodeAnalysis, MutationResponse, MemoryContext, OptimizationObjective,
)


class AIProviderBase(ABC):
    """
    Abstract base for AI mutation providers.

    Implementations must handle retries, timeouts, and error recovery.
    """

    @abstractmethod
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
        """
        Generate mutation candidates for the given source code.

        Args:
            source_code: The original source code.
            language: Programming language name.
            analysis: Code analysis results.
            objective: The optimization objective.
            memory_context: Relevant evolutionary memory.
            previous_failures: Summaries of previous failed attempts.
            candidate_count: Number of candidates to generate.

        Returns:
            MutationResponse with candidate implementations.
        """
        ...

    @abstractmethod
    def explain_change(
        self,
        original: str,
        candidate: str,
        language: str,
    ) -> str:
        """
        Generate a human-readable explanation of the differences.

        Args:
            original: Original source code.
            candidate: Candidate source code.
            language: Programming language.

        Returns:
            A text explanation of the changes.
        """
        ...

    @abstractmethod
    def summarize_experiment(
        self,
        experiment_summary: dict,
    ) -> str:
        """
        Generate a summary of an experiment for evolutionary memory.

        Args:
            experiment_summary: Dict containing experiment results.

        Returns:
            A text summary suitable for memory storage.
        """
        ...

    @abstractmethod
    def check_availability(self) -> tuple[bool, str]:
        """
        Check if the provider is configured and reachable.

        Returns:
            Tuple of (is_available, status_message).
        """
        ...

    def analyze_code(
        self,
        source_code: str,
        language: str,
        objective: OptimizationObjective = OptimizationObjective.BALANCED,
        static_context: Optional[dict] = None,
    ) -> dict:
        """
        Analyze code structure, complexity, bottlenecks, and correctness invariants.

        Args:
            source_code: Target code content.
            language: Programming language.
            objective: Target optimization objective.
            static_context: Optional AST or static analysis dictionary.

        Returns:
            Structured analysis result dictionary.
        """
        return {
            "language": language,
            "structural_summary": {"public_interface": []},
            "complexity": {"estimated_time_complexity": "unknown"},
            "optimization_suggestions": [],
            "correctness_invariants": [],
        }

    def explain_failure(
        self,
        original: str,
        candidate: str,
        failure_reasons: list[str],
        language: str,
    ) -> str:
        """
        Explain a failed mutation or regression.

        Args:
            original: Original source code.
            candidate: Candidate code that failed.
            failure_reasons: List of test or validation error messages.
            language: Target programming language.

        Returns:
            A human-readable explanation and reusable lesson.
        """
        reasons = "; ".join(failure_reasons) if failure_reasons else "Unknown failure"
        return f"Candidate failed validation or tests in {language}: {reasons}"

    def explain_optimization(
        self,
        original: str,
        candidate: str,
        benchmark_info: dict,
        language: str,
    ) -> str:
        """
        Explain verified optimizations and empirical benchmark findings.

        Args:
            original: Original source code.
            candidate: Candidate code.
            benchmark_info: Empirical benchmark measurements.
            language: Target programming language.

        Returns:
            A human-readable explanation of the optimization mechanisms.
        """
        return self.explain_change(original, candidate, language)

    def interpret_benchmark(
        self,
        benchmark_data: dict,
        baseline_data: Optional[dict] = None,
    ) -> str:
        """
        Interpret empirical benchmark results and assess statistical confidence.

        Args:
            benchmark_data: Candidate benchmark statistics.
            baseline_data: Optional baseline benchmark measurements.

        Returns:
            A technical assessment of the measured performance delta.
        """
        return f"Benchmark completed with median runtime {benchmark_data.get('median_time', 'N/A')}s."

    def verify_candidate(
        self,
        prompt: str,
        system_instruction: str = "",
    ) -> str:
        """
        Execute logical correctness reasoning on candidate code.

        Args:
            prompt: Structured logical verification prompt.
            system_instruction: Optional system instruction.

        Returns:
            JSON string containing structured logical verification findings.
        """
        return ""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of this provider."""
        ...

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Return the configured model identifier."""
        ...
