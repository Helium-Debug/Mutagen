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
