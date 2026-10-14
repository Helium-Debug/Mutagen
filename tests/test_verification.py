"""
Comprehensive Unit & Integration Test Suite for the MUTAGEN Verification Layer.

Tests all stages and requirements:
1. Syntax Verification (valid -> PASS, malformed -> FAIL)
2. Semantic Static Analysis (undefined vars, call mismatch, unreachable code, div-by-zero)
3. Test Verification (regression detection: original vs candidate)
4. Runtime Sandbox Verification (success, exception, timeout)
5. Adversarial & Differential Testing (regression detection e.g. fib(n-3))
6. Complexity Analysis (improvement vs regression)
7. Gemma 4 Reasoning Layer (PASS, FAIL, UNCERTAIN, and offline fallback to UNAVAILABLE/REVIEW)
8. Correctness Priority (performance +40% with FAIL -> REJECT; +15% with PASS -> ACCEPT)
9. Machine-Readable JSON Output (Section 16 schema)
10. Terminal Output & Report Generation (Sections 14 and 15)
"""

import pytest
from unittest.mock import MagicMock, patch

from mutagen.verification.schemas import (
    CheckStatus,
    ComplexityCheckResult,
    DiagnosticItem,
    DifferentialResult,
    LogicalAnalysisResult,
    MutationAnalysis,
    RuntimeCheckResult,
    SemanticCheckResult,
    SyntaxCheckResult,
    TestCheckResult,
    VerificationReport,
    VerificationVerdict,
)
from mutagen.verification.syntax import SyntaxVerifier
from mutagen.verification.semantic import SemanticVerifier
from mutagen.verification.runtime import RuntimeVerifier
from mutagen.verification.test_verifier import TestVerifier
from mutagen.verification.differential import DifferentialTester
from mutagen.verification.complexity import ComplexityVerifier
from mutagen.verification.logical import LogicalVerifier
from mutagen.verification.verdict import VerdictEvaluator
from mutagen.verification.report import (
    format_terminal_stages,
    format_verification_report,
    to_machine_dict,
)
from mutagen.verification.pipeline import VerificationPipeline
from mutagen.schemas import MutationCandidate, MutationStrategy, ValidationResult
from mutagen.evolution.fitness import FitnessEvaluator
from mutagen.sandbox.docker_manager import DockerSandbox, SandboxResult


# ── 1. Syntax Verification ────────────────────────────────────

def test_syntax_verifier_valid_code():
    verifier = SyntaxVerifier()
    code = "def add(a, b):\n    return a + b\n"
    res = verifier.verify(code)
    assert res.passed is True
    assert res.status == CheckStatus.PASS
    assert res.line is None


def test_syntax_verifier_malformed_code():
    verifier = SyntaxVerifier()
    broken_code = "def broken(:\n    return 42"
    res = verifier.verify(broken_code)
    assert res.passed is False
    assert res.status == CheckStatus.FAIL
    assert res.severity == "critical"
    assert res.line == 1
    assert "SyntaxError" in res.message or "invalid syntax" in res.message.lower() or "expected" in res.message.lower()


# ── 2. Semantic Verification ──────────────────────────────────

def test_semantic_verifier_valid_code():
    verifier = SemanticVerifier()
    code = """
def calculate(x, y):
    total = x + y
    return total * 2
"""
    res = verifier.verify(code)
    assert res.passed is True
    assert len(res.diagnostics) == 0


def test_semantic_verifier_undefined_variable():
    verifier = SemanticVerifier()
    code = """
def compute(x):
    return x + undefined_variable_abc
"""
    res = verifier.verify(code)
    assert res.passed is False
    assert any("undefined_variable_abc" in d.message for d in res.diagnostics)
    assert any(d.severity == "high" for d in res.diagnostics)


def test_semantic_verifier_call_arg_count_mismatch():
    verifier = SemanticVerifier()
    code = """
def helper(a, b):
    return a + b

def run():
    return helper(1, 2, 3, 4)
"""
    res = verifier.verify(code)
    assert res.passed is False
    assert any("arguments" in d.message.lower() for d in res.diagnostics)


def test_semantic_verifier_unreachable_code():
    verifier = SemanticVerifier()
    code = """
def early_exit(val):
    if val > 0:
        return 1
        print("This is unreachable")
    return 0
"""
    res = verifier.verify(code)
    assert res.passed is False
    assert any("unreachable" in d.message.lower() for d in res.diagnostics)


def test_semantic_verifier_constant_divide_by_zero():
    verifier = SemanticVerifier()
    code = """
def bad_math():
    x = 10 / 0
    return x
"""
    res = verifier.verify(code)
    assert res.passed is False
    assert any("division by zero" in d.message.lower() for d in res.diagnostics)


# ── 3. Test Verification ──────────────────────────────────────

def test_test_verifier_no_regression():
    from mutagen.schemas import TestResult
    mock_runner = MagicMock()
    mock_runner.run_tests.return_value = TestResult(
        candidate_id="cand_1",
        total_tests=5,
        passed=5,
        failed=0,
    )
    orig_result = TestResult(
        candidate_id="original",
        total_tests=5,
        passed=5,
        failed=0,
    )
    verifier = TestVerifier(test_runner=mock_runner)
    res = verifier.verify(
        candidate_id="cand_1",
        original_code="def fn(): pass",
        candidate_code="def fn(): return 1",
        test_command="pytest",
        original_test_result=orig_result,
    )
    assert res.passed is True
    assert res.has_regression is False
    assert res.candidate_tests["passed"] == 5


def test_test_verifier_regression_detected():
    from mutagen.schemas import TestResult
    mock_runner = MagicMock()
    mock_runner.run_tests.return_value = TestResult(
        candidate_id="cand_1",
        total_tests=5,
        passed=4,
        failed=1,
    )
    orig_result = TestResult(
        candidate_id="original",
        total_tests=5,
        passed=5,
        failed=0,
    )
    verifier = TestVerifier(test_runner=mock_runner)
    res = verifier.verify(
        candidate_id="cand_1",
        original_code="def fn(): pass",
        candidate_code="def fn(): return 1",
        test_command="pytest",
        original_test_result=orig_result,
    )
    assert res.passed is False
    assert res.has_regression is True
    assert res.candidate_tests["failed"] == 1


# ── 4. Runtime Verification ───────────────────────────────────

def test_runtime_verifier_success():
    sandbox = MagicMock(spec=DockerSandbox)
    sandbox.execute_python.return_value = SandboxResult(
        exit_code=0,
        stdout="OK",
        stderr="",
        duration_seconds=0.01,
        timed_out=False,
    )

    verifier = RuntimeVerifier(sandbox=sandbox)
    res = verifier.verify("def add(a, b): return a + b")
    assert res.passed is True
    assert res.exit_code == 0
    assert not res.timed_out


def test_runtime_verifier_runtime_error():
    sandbox = MagicMock(spec=DockerSandbox)
    sandbox.execute_python.return_value = SandboxResult(
        exit_code=1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
        duration_seconds=0.01,
        timed_out=False,
    )

    verifier = RuntimeVerifier(sandbox=sandbox)
    res = verifier.verify("x = 1 / 0")
    assert res.passed is False
    assert res.exit_code == 1
    assert "ZeroDivisionError" in res.error_message


def test_runtime_verifier_timeout():
    sandbox = MagicMock(spec=DockerSandbox)
    sandbox.execute_python.return_value = SandboxResult(
        exit_code=124,
        stdout="",
        stderr="",
        duration_seconds=5.0,
        timed_out=True,
        error="Timed out",
    )

    verifier = RuntimeVerifier(sandbox=sandbox)
    res = verifier.verify("while True: pass")
    assert res.passed is False
    assert res.timed_out is True


# ── 5. Differential / Edge-Case Testing ────────────────────────

def test_differential_testing_equivalent_functions():
    tester = DifferentialTester()
    original = """
def calculate(n):
    total = 0
    for i in range(n):
        total += i
    return total
"""
    # Optimized using mathematical sum formula n*(n-1)//2
    candidate = """
def calculate(n):
    if n <= 0:
        return 0
    return n * (n - 1) // 2
"""
    res = tester.test(original, candidate)
    assert res.passed is True
    assert res.has_regression is False
    assert len(res.discrepancies) == 0


def test_differential_testing_detects_fibonacci_regression():
    tester = DifferentialTester()
    original = """
def fibonacci(n):
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 2)
"""
    # Flawed candidate with n-3 instead of n-2
    candidate = """
def fibonacci(n):
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 3)
"""
    res = tester.test(original, candidate)
    assert res.passed is False
    assert res.has_regression is True
    assert len(res.discrepancies) > 0
    # Confirm discrepancy details
    disc = res.discrepancies[0]
    assert disc["status"] == "REGRESSION"
    assert disc["original_output"] != disc["candidate_output"]


# ── 6. Complexity Verification ────────────────────────────────

def test_complexity_improvement():
    verifier = ComplexityVerifier()
    # Nested loops O(n^2)
    orig_code = """
def search(items):
    out = []
    for x in items:
        for y in items:
            out.append(x + y)
    return out
"""
    # Single loop O(n)
    cand_code = """
def search(items):
    return [x * 2 for x in items]
"""
    res = verifier.verify(orig_code, cand_code)
    assert res.time_regression is False
    assert res.status in ("IMPROVED", "PRESERVED")


def test_complexity_regression():
    verifier = ComplexityVerifier()
    # Single loop O(n)
    orig_code = """
def search(items):
    return [x * 2 for x in items]
"""
    # Triple nested loops O(n^3)
    cand_code = """
def search(items):
    out = []
    for x in items:
        for y in items:
            for z in items:
                out.append(x + y + z)
    return out
"""
    res = verifier.verify(orig_code, cand_code)
    assert res.time_regression is True
    assert res.status in ("REGRESSED", "REGRESSION")


# ── 7. Logical Verification (Gemma 4 & Fallback) ──────────────

def test_logical_verifier_gemma_pass():
    mock_ai = MagicMock()
    mock_ai.verify_candidate.return_value = {
        "verdict": "PASS",
        "confidence": 0.95,
        "logical_correctness": {"status": "PASS", "reason": "Algorithm preserved"},
        "behavior_preservation": {"status": "PASS", "reason": "Outputs match"},
        "edge_cases": [{"case": "n=0", "risk": "LOW", "reason": "Handled"}],
        "detected_errors": [],
        "suggested_tests": ["test(0)"],
        "recommendation": "ACCEPT",
    }

    verifier = LogicalVerifier(ai_provider=mock_ai)
    res = verifier.verify(
        original_code="def f(x): return x * 2",
        candidate_code="def f(x): return x << 1",
        diff="+ return x << 1",
        tests="assert f(2) == 4",
    )

    assert res.verdict == CheckStatus.PASS
    assert res.confidence == 0.95
    assert res.recommendation == VerificationVerdict.ACCEPT


def test_logical_verifier_gemma_fail():
    mock_ai = MagicMock()
    mock_ai.verify_candidate.return_value = {
        "verdict": "FAIL",
        "confidence": 0.92,
        "logical_correctness": {"status": "FAIL", "reason": "Negative inputs return wrong answer"},
        "behavior_preservation": {"status": "FAIL", "reason": "Sign inverted"},
        "edge_cases": [{"case": "x < 0", "risk": "HIGH", "reason": "Fails"}],
        "detected_errors": [
            {
                "type": "LOGICAL",
                "severity": "HIGH",
                "location": "line 2",
                "description": "Negative numbers produce incorrect sign",
            }
        ],
        "suggested_tests": ["f(-5)"],
        "recommendation": "REJECT",
    }

    verifier = LogicalVerifier(ai_provider=mock_ai)
    res = verifier.verify(
        original_code="def f(x): return abs(x)",
        candidate_code="def f(x): return x",
        diff="- return abs(x)\n+ return x",
        tests="",
    )

    assert res.verdict == CheckStatus.FAIL
    assert res.recommendation == VerificationVerdict.REJECT
    assert len(res.detected_errors) == 1


def test_logical_verifier_offline_fallback():
    """
    Section 20:
    If Gemma 4 is unavailable:
    Do not fabricate a result.
    Instead return:
    LOGICAL VERIFICATION: UNAVAILABLE
    FINAL VERDICT: REVIEW
    """
    mock_ai = MagicMock()
    mock_ai.verify_candidate.side_effect = ConnectionError("Could not connect to Ollama")

    verifier = LogicalVerifier(ai_provider=mock_ai)
    res = verifier.verify(
        original_code="def f(x): return x",
        candidate_code="def f(x): return x",
        diff="",
        tests="",
    )

    assert res.verdict in (CheckStatus.UNAVAILABLE, CheckStatus.UNCERTAIN)
    assert res.confidence == 0.0
    assert res.recommendation == VerificationVerdict.REVIEW
    assert "UNAVAILABLE" in res.logical_correctness.get("reason", "").upper()


# ── 8. Verdict Decision & Priority: Performance vs Correctness ─

def test_verdict_rejects_performance_when_correctness_fails():
    """
    Section 12: Performance must never compensate for incorrectness.
    Candidate A: Performance +40%, Correctness: FAIL -> REJECT.
    """
    evaluator = VerdictEvaluator()

    syntax = SyntaxCheckResult(passed=True)
    semantic = SemanticCheckResult(passed=True)
    tests = TestCheckResult(passed=True, candidate_tests={"passed": 10, "failed": 0})
    runtime = RuntimeCheckResult(passed=True)
    differential = DifferentialResult(passed=False, has_regression=True, discrepancies=[{"status": "REGRESSION"}])
    complexity = ComplexityCheckResult(status="IMPROVED", time_regression=False)
    logic = LogicalAnalysisResult(
        verdict=CheckStatus.FAIL,
        confidence=0.95,
        recommendation=VerificationVerdict.REJECT,
        detected_errors=[{"type": "LOGICAL", "description": "Output mismatch on boundary"}],
    )

    verdict, score, rejections, reviews = evaluator.evaluate(
        syntax=syntax,
        semantic=semantic,
        tests=tests,
        runtime=runtime,
        differential=differential,
        complexity=complexity,
        logic=logic,
    )

    assert verdict == VerificationVerdict.REJECT
    assert score == 0.0
    assert len(rejections) > 0


def test_verdict_accepts_when_all_pass():
    evaluator = VerdictEvaluator()

    syntax = SyntaxCheckResult(passed=True)
    semantic = SemanticCheckResult(passed=True)
    tests = TestCheckResult(passed=True, candidate_tests={"passed": 10, "failed": 0})
    runtime = RuntimeCheckResult(passed=True)
    differential = DifferentialResult(passed=True, has_regression=False)
    complexity = ComplexityCheckResult(status="IMPROVED", time_regression=False)
    logic = LogicalAnalysisResult(
        verdict=CheckStatus.PASS,
        confidence=0.90,
        recommendation=VerificationVerdict.ACCEPT,
    )

    verdict, score, rejections, reviews = evaluator.evaluate(
        syntax=syntax,
        semantic=semantic,
        tests=tests,
        runtime=runtime,
        differential=differential,
        complexity=complexity,
        logic=logic,
    )

    assert verdict == VerificationVerdict.ACCEPT
    assert score >= 0.85
    assert len(rejections) == 0


def test_verdict_review_when_uncertain():
    evaluator = VerdictEvaluator()

    syntax = SyntaxCheckResult(passed=True)
    semantic = SemanticCheckResult(passed=True)
    tests = TestCheckResult(passed=True)
    runtime = RuntimeCheckResult(passed=True)
    differential = DifferentialResult(passed=True)
    complexity = ComplexityCheckResult(status="PRESERVED")
    # Low confidence / uncertain logical review
    logic = LogicalAnalysisResult(
        verdict=CheckStatus.UNCERTAIN,
        confidence=0.55,
        recommendation=VerificationVerdict.REVIEW,
        edge_cases=[{"case": "max recursion", "risk": "MEDIUM", "reason": "unverified"}],
    )

    verdict, score, rejections, reviews = evaluator.evaluate(
        syntax=syntax,
        semantic=semantic,
        tests=tests,
        runtime=runtime,
        differential=differential,
        complexity=complexity,
        logic=logic,
    )

    assert verdict == VerificationVerdict.REVIEW
    assert len(reviews) > 0


# ── 9. Fitness Evaluator Gate ─────────────────────────────────

def test_fitness_evaluator_rejects_candidate_when_verification_fails():
    fitness_eval = FitnessEvaluator()

    cand = MutationCandidate(
        candidate_id="cand_test",
        source_code="def f(): pass",
        strategy=MutationStrategy.ALGORITHMIC,
    )
    val = ValidationResult(candidate_id=cand.candidate_id, is_valid=True)

    failed_report = VerificationReport(
        candidate_id=cand.candidate_id,
        syntax=SyntaxCheckResult(passed=True),
        semantic=SemanticCheckResult(passed=True),
        tests=TestCheckResult(passed=True),
        runtime=RuntimeCheckResult(passed=True),
        differential=DifferentialResult(passed=False, has_regression=True),
        complexity=ComplexityCheckResult(status="IMPROVED"),
        logic=LogicalAnalysisResult(verdict=CheckStatus.FAIL, confidence=0.9, recommendation=VerificationVerdict.REJECT),
        final_verdict=VerificationVerdict.REJECT,
        verification_score=0.0,
        rejection_reasons=["Differential test failed: Output mismatch"],
    )

    fitness = fitness_eval.evaluate(
        candidate_id=cand.candidate_id,
        validation=val,
        test_result=None,
        benchmark=None,
        baseline_benchmark=None,
        verification_report=failed_report,
    )

    assert fitness.is_eligible is False
    assert fitness.overall_score == 0.0
    assert any("Verification rejected" in r for r in fitness.rejection_reasons)


# ── 10. Machine-Readable JSON & Terminal Report ───────────────

def test_machine_dict_and_report_output():
    report = VerificationReport(
        candidate_id="MUT-042",
        syntax=SyntaxCheckResult(passed=True),
        semantic=SemanticCheckResult(passed=True),
        tests=TestCheckResult(passed=True, candidate_tests={"passed": 48, "failed": 0}),
        runtime=RuntimeCheckResult(passed=True),
        differential=DifferentialResult(passed=True, has_regression=False),
        complexity=ComplexityCheckResult(
            status="IMPROVED",
            time_before="O(n²)",
            time_after="O(n)",
            space_before="O(n)",
            space_after="O(1)",
        ),
        logic=LogicalAnalysisResult(
            verdict=CheckStatus.PASS,
            confidence=0.94,
            recommendation=VerificationVerdict.ACCEPT,
            logical_correctness={"status": "PASS", "reason": "Correctness verified"},
        ),
        final_verdict=VerificationVerdict.ACCEPT,
        verification_score=0.96,
        performance_improvement_percent=18.4,
    )

    # 1. Terminal stages
    stages = format_terminal_stages(report)
    assert len(stages) == 7
    assert "[1/7] Syntax verification ........ PASS" in stages[0]
    assert "[5/7] Logical verification ...... PASS" in stages[4]

    # 2. Complete report
    txt_report = format_verification_report(report)
    assert "MUTAGEN VERIFICATION REPORT" in txt_report
    assert "Candidate: MUT-042" in txt_report
    assert "48 / 48 PASS" in txt_report
    assert "O(n²) → O(n)" in txt_report
    assert "FINAL VERDICT: ACCEPT" in txt_report

    # 3. Machine JSON
    data = to_machine_dict(report)
    assert data["candidate_id"] == "MUT-042"
    assert data["syntax"]["status"] == "PASS"
    assert data["tests"]["passed"] == 48
    assert data["complexity"]["time"]["before"] == "O(n²)"
    assert data["complexity"]["time"]["after"] == "O(n)"
    assert data["final_verdict"] == "ACCEPT"


# ── 11. End-to-End Verification Pipeline ──────────────────────

def test_pipeline_fails_fast_on_syntax_error():
    mock_ai = MagicMock()
    pipeline = VerificationPipeline(ai_provider=mock_ai)

    cand = MutationCandidate(
        candidate_id="mut_syntax_err",
        source_code="def broken(:\n    pass",
        strategy=MutationStrategy.ALGORITHMIC,
    )

    report = pipeline.verify(
        candidate=cand,
        original_code="def valid(): pass",
    )

    assert report.final_verdict == VerificationVerdict.REJECT
    assert report.syntax.passed is False
    # AI provider was NOT called due to fail-fast
    assert mock_ai.verify_candidate.call_count == 0


def test_logical_verifier_handles_dict_suggested_tests():
    mock_ai = MagicMock()
    mock_ai.verify_candidate.return_value = {
        "verdict": "PASS",
        "confidence": 0.92,
        "logical_correctness": {"status": "PASS", "reason": "Equivalent logic"},
        "behavior_preservation": {"status": "PASS", "reason": "Preserved"},
        "edge_cases": [{"case": "n=35", "risk": "LOW", "reason": "Fits in int"}],
        "detected_errors": [],
        "suggested_tests": [
            {"description": "Test a much larger value where optimization is evident", "input": 35},
            {"case": "Test negative input", "risk": "LOW"},
        ],
        "recommendation": "ACCEPT",
    }

    verifier = LogicalVerifier(ai_provider=mock_ai)
    res = verifier.verify("def f(x): pass", "def f(x): return x", "", "")

    assert res.verdict == CheckStatus.PASS
    assert len(res.suggested_tests) == 2
    assert "35" in str(res.suggested_tests[0])

