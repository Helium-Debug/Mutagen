"""
Complexity Verification Stage for MUTAGEN.

Compares time and space complexity estimates between original and candidate code
to ensure algorithmic efficiency is preserved or improved without regressions.
"""

from __future__ import annotations

from typing import Optional

from mutagen.schemas import CodeAnalysis
from mutagen.verification.schemas import ComplexityCheckResult

ORDER_MAP = {
    "O(1)": 1,
    "O(log n)": 2,
    "O(n)": 3,
    "O(n log n)": 4,
    "O(n²)": 5,
    "O(n^2)": 5,
    "O(n³)": 6,
    "O(n^3)": 6,
    "O(2^n)": 7,
    "O(n!)": 8,
}


def _complexity_rank(comp_str: str) -> int:
    """Map complexity string to integer order for comparison."""
    for key, rank in ORDER_MAP.items():
        if key in comp_str:
            return rank
    return 3  # Default to linear if unspecified


class ComplexityVerifier:
    """Verifies that code preserves or improves algorithmic complexity."""

    def verify(
        self,
        original_analysis: Optional[CodeAnalysis],
        candidate_analysis: Optional[CodeAnalysis],
    ) -> ComplexityCheckResult:
        """
        Compare algorithmic complexity between original and candidate code.

        Returns:
            ComplexityCheckResult with before/after Big-O notation and regression flags.
        """
        if not original_analysis or not candidate_analysis:
            return ComplexityCheckResult(
                status="PRESERVED",
                time_before="O(1)",
                time_after="O(1)",
                space_before="O(1)",
                space_after="O(1)",
            )

        if isinstance(original_analysis, str):
            from mutagen.analysis.python_analyzer import PythonAnalyzer
            original_analysis = PythonAnalyzer().analyze(original_analysis, "orig.py")
        if isinstance(candidate_analysis, str):
            from mutagen.analysis.python_analyzer import PythonAnalyzer
            candidate_analysis = PythonAnalyzer().analyze(candidate_analysis, "cand.py")

        orig_time = getattr(original_analysis, "estimated_time_complexity", None) or "O(1)"
        cand_time = getattr(candidate_analysis, "estimated_time_complexity", None) or "O(1)"
        orig_space = getattr(original_analysis, "estimated_space_complexity", None) or "O(1)"
        cand_space = getattr(candidate_analysis, "estimated_space_complexity", None) or "O(1)"

        rank_orig_time = _complexity_rank(orig_time)
        rank_cand_time = _complexity_rank(cand_time)

        rank_orig_space = _complexity_rank(orig_space)
        rank_cand_space = _complexity_rank(cand_space)

        time_regression = rank_cand_time > rank_orig_time
        space_regression = rank_cand_space > rank_orig_space

        time_improved = rank_cand_time < rank_orig_time
        space_improved = rank_cand_space < rank_orig_space

        if time_regression or space_regression:
            status = "REGRESSION"
        elif time_improved or space_improved:
            status = "IMPROVED"
        else:
            status = "PRESERVED"

        return ComplexityCheckResult(
            status=status,
            time_before=orig_time.split()[0],
            time_after=cand_time.split()[0],
            space_before=orig_space.split()[0],
            space_after=cand_space.split()[0],
            time_regression=time_regression,
            space_regression=space_regression,
        )
