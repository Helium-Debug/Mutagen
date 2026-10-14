"""
MUTAGEN Semantic & Logical Verification Layer.

A modular correctness verification system designed to evaluate syntax,
semantics, unit tests, runtime stability, adversarial differential tests,
algorithmic complexity, and Gemma 4 reasoning-based logical correctness.
"""

from mutagen.verification.schemas import (
    CheckStatus,
    ComplexityCheckResult,
    DiagnosticItem,
    DifferentialResult,
    LogicalAnalysisResult,
    MutationAnalysis,
    RuntimeCheckResult,
    SemanticCheckResult,
    Severity,
    SyntaxCheckResult,
    TestCheckResult,
    VerificationReport,
    VerificationVerdict,
)
from mutagen.verification.syntax import SyntaxVerifier
from mutagen.verification.semantic import SemanticVerifier
from mutagen.verification.test_verifier import TestVerifier
from mutagen.verification.runtime import RuntimeVerifier
from mutagen.verification.differential import DifferentialTester
from mutagen.verification.logical import LogicalVerifier, build_logical_verification_prompt
from mutagen.verification.complexity import ComplexityVerifier
from mutagen.verification.verdict import VerdictEvaluator
from mutagen.verification.report import (
    format_terminal_stages,
    format_verification_report,
    to_machine_dict,
)
from mutagen.verification.pipeline import VerificationPipeline

__all__ = [
    "CheckStatus",
    "ComplexityCheckResult",
    "ComplexityVerifier",
    "DiagnosticItem",
    "DifferentialResult",
    "DifferentialTester",
    "LogicalAnalysisResult",
    "LogicalVerifier",
    "MutationAnalysis",
    "RuntimeCheckResult",
    "RuntimeVerifier",
    "SemanticCheckResult",
    "SemanticVerifier",
    "Severity",
    "SyntaxCheckResult",
    "SyntaxVerifier",
    "TestCheckResult",
    "TestVerifier",
    "VerdictEvaluator",
    "VerificationPipeline",
    "VerificationReport",
    "VerificationVerdict",
    "build_logical_verification_prompt",
    "format_terminal_stages",
    "format_verification_report",
    "to_machine_dict",
]
