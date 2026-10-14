"""
Data schemas for the MUTAGEN Verification Layer.

Defines structured models for syntax, semantic, test, runtime,
differential, logical, and complexity verification results,
as well as the final verdict and report.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class VerificationVerdict(str, Enum):
    """Final decision on a mutation candidate."""
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REVIEW = "REVIEW"


class CheckStatus(str, Enum):
    """Status of an individual verification check."""
    PASS = "PASS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"
    UNAVAILABLE = "UNAVAILABLE"
    IMPROVED = "IMPROVED"
    PRESERVED = "PRESERVED"
    REGRESSION = "REGRESSION"


class Severity(str, Enum):
    """Severity of a detected issue."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DiagnosticItem(BaseModel):
    """Structured diagnostic reported by verification stages."""
    category: str = "general"
    status: str = "failed"
    severity: str = "medium"
    message: str = ""
    line: Optional[int] = None
    column: Optional[int] = None
    location: Optional[dict[str, Any]] = None


class SyntaxCheckResult(BaseModel):
    """Result of syntax and compilation verification."""
    category: str = "syntax"
    status: CheckStatus = CheckStatus.PASS
    severity: Optional[Severity] = None
    line: Optional[int] = None
    column: Optional[int] = None
    message: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS


class SemanticCheckResult(BaseModel):
    """Result of semantic static analysis and contract validation."""
    category: str = "semantic"
    status: CheckStatus = CheckStatus.PASS
    diagnostics: list[DiagnosticItem] = Field(default_factory=list)
    summary: str = "Semantic checks passed"

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS


class TestCheckResult(BaseModel):
    """Result of unit / integration test regression analysis."""
    __test__ = False
    status: CheckStatus = CheckStatus.PASS
    original_tests: dict[str, int] = Field(default_factory=lambda: {"passed": 0, "failed": 0})
    candidate_tests: dict[str, int] = Field(default_factory=lambda: {"passed": 0, "failed": 0})
    has_regression: bool = False
    details: str = ""

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS and not self.has_regression


class RuntimeCheckResult(BaseModel):
    """Result of runtime execution and sandbox verification."""
    status: CheckStatus = CheckStatus.PASS
    exit_code: int = 0
    timed_out: bool = False
    error_message: Optional[str] = None
    traceback: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS and self.exit_code == 0 and not self.timed_out


class DifferentialResult(BaseModel):
    """Result of adversarial & differential testing against original code."""
    status: CheckStatus = CheckStatus.PASS
    inputs_tested: int = 0
    discrepancies: list[dict[str, Any]] = Field(default_factory=list)
    properties_tested: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def has_regression(self) -> bool:
        return len(self.discrepancies) > 0

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS and not self.has_regression


class LogicalAnalysisResult(BaseModel):
    """Result of Gemma 4 reasoning-based logical verification."""
    verdict: CheckStatus = CheckStatus.PASS
    confidence: float = 1.0
    logical_correctness: dict[str, Any] = Field(
        default_factory=lambda: {"status": "PASS", "reason": "No logical flaws detected"}
    )
    behavior_preservation: dict[str, Any] = Field(
        default_factory=lambda: {"status": "PASS", "reason": "Behavior preserved"}
    )
    edge_cases: list[dict[str, Any]] = Field(default_factory=list)
    detected_errors: list[dict[str, Any]] = Field(default_factory=list)
    suggested_tests: list[Any] = Field(default_factory=list)
    recommendation: VerificationVerdict = VerificationVerdict.ACCEPT
    raw_model_response: Optional[str] = None


class ComplexityCheckResult(BaseModel):
    """Result of time & space complexity regression analysis."""
    status: str = "PRESERVED"
    time_before: str = "O(1)"
    time_after: str = "O(1)"
    space_before: str = "O(1)"
    space_after: str = "O(1)"
    time_regression: bool = False
    space_regression: bool = False


class MutationAnalysis(BaseModel):
    """Detailed metadata for a candidate mutation."""
    mutation_id: str
    mutation_type: str = "general"
    changed_lines: list[int] = Field(default_factory=list)
    affected_functions: list[str] = Field(default_factory=list)
    behavioral_risk: str = "LOW"
    verification: str = "PASS"


class VerificationReport(BaseModel):
    """
    Complete, composite report generated by the MUTAGEN Verification Layer.
    """
    candidate_id: str
    syntax: SyntaxCheckResult = Field(default_factory=SyntaxCheckResult)
    semantic: SemanticCheckResult = Field(default_factory=SemanticCheckResult)
    tests: TestCheckResult = Field(default_factory=TestCheckResult)
    runtime: RuntimeCheckResult = Field(default_factory=RuntimeCheckResult)
    differential: DifferentialResult = Field(default_factory=DifferentialResult)
    logic: LogicalAnalysisResult = Field(default_factory=LogicalAnalysisResult)
    regression: CheckStatus = CheckStatus.PASS
    complexity: ComplexityCheckResult = Field(default_factory=ComplexityCheckResult)
    mutation_analysis: Optional[MutationAnalysis] = None
    verification_score: float = 1.0
    final_verdict: VerificationVerdict = VerificationVerdict.ACCEPT
    rejection_reasons: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    performance_improvement_percent: float = 0.0
    duration_seconds: float = 0.0
