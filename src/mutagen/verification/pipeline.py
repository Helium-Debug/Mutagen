"""
Modular Verification Pipeline for MUTAGEN.

Orchestrates all verification stages:
1. Syntax Verification
2. Semantic Static Analysis
3. Unit / Integration Test Verification
4. Secure Sandbox Runtime Verification
5. Adversarial & Differential Testing
6. Complexity Analysis & Regression Detection
7. Gemma 4 Reasoning-Based Logical Verification
8. Composite Verdict & Correctness Scoring
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from mutagen.ai.base import AIProviderBase
from mutagen.core.logging import get_logger
from mutagen.sandbox.docker_manager import DockerSandbox
from mutagen.schemas import (
    CodeAnalysis, MutationCandidate, TestResult,
)
from mutagen.testing.test_runner import TestRunner
from mutagen.verification.complexity import ComplexityVerifier
from mutagen.verification.differential import DifferentialTester
from mutagen.verification.logical import LogicalVerifier
from mutagen.verification.report import format_terminal_stages
from mutagen.verification.runtime import RuntimeVerifier
from mutagen.verification.test_verifier import TestVerifier
from mutagen.verification.schemas import (
    CheckStatus, ComplexityCheckResult, DifferentialResult,
    LogicalAnalysisResult, MutationAnalysis, RuntimeCheckResult,
    SemanticCheckResult, SyntaxCheckResult, TestCheckResult,
    VerificationReport, VerificationVerdict,
)
from mutagen.verification.semantic import SemanticVerifier
from mutagen.verification.syntax import SyntaxVerifier
from mutagen.verification.verdict import VerdictEvaluator

logger = get_logger("verification.pipeline")


class VerificationPipeline:
    """
    Dedicated Code Correctness Verification System for MUTAGEN.

    Ensures that mutation candidates are not accepted merely because they
    run faster or pass superficial tests, but because they strictly preserve
    logical correctness, semantics, and behavioral invariants.
    """

    def __init__(
        self,
        sandbox: Optional[DockerSandbox] = None,
        ai_provider: Optional[AIProviderBase] = None,
        test_runner: Optional[TestRunner] = None,
        timeout: int = 15,
    ):
        self.sandbox = sandbox or DockerSandbox()
        self.ai_provider = ai_provider
        self.test_runner = test_runner or TestRunner(self.sandbox, timeout=timeout)
        self.timeout = timeout

        # Subsystems
        self.syntax_verifier = SyntaxVerifier()
        self.semantic_verifier = SemanticVerifier()
        self.test_verifier = TestVerifier(self.test_runner)
        self.runtime_verifier = RuntimeVerifier(sandbox, timeout=timeout)
        self.differential_tester = DifferentialTester(sandbox, timeout=timeout)
        self.logical_verifier = LogicalVerifier(ai_provider)
        self.complexity_verifier = ComplexityVerifier()
        self.verdict_evaluator = VerdictEvaluator()

    def verify(
        self,
        candidate: MutationCandidate,
        original_code: str,
        original_analysis: Optional[CodeAnalysis] = None,
        candidate_analysis: Optional[CodeAnalysis] = None,
        diff_text: str = "",
        test_code: Optional[str] = None,
        test_command: Optional[str] = None,
        original_test_result: Optional[TestResult] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> VerificationReport:
        """
        Execute the full verification pipeline on a mutation candidate.

        Fails fast on deterministic errors (syntax/critical semantic/runtime)
        before making expensive LLM calls.
        """
        start_time = time.time()
        cand_id = candidate.candidate_id
        candidate_code = candidate.source_code

        def notify(stage: str, msg: str):
            if progress_callback:
                progress_callback(stage, msg)

        # ── Stage 1: Syntax Verification ──────────────────────
        notify("syntax", f"[1/7] Syntax verification ........ RUNNING")
        syntax_res = self.syntax_verifier.verify(candidate_code)
        if not syntax_res.passed:
            notify("syntax", f"[1/7] Syntax verification ........ FAIL")
            return self._build_early_rejection(
                cand_id, syntax=syntax_res,
                rejection_reason=f"Syntax error on line {syntax_res.line}: {syntax_res.message}",
                duration=time.time() - start_time
            )
        notify("syntax", f"[1/7] Syntax verification ........ PASS")

        # ── Stage 2: Semantic Verification ────────────────────
        notify("semantic", f"[2/7] Semantic verification ..... RUNNING")
        semantic_res = self.semantic_verifier.verify(candidate_code)
        if not semantic_res.passed:
            notify("semantic", f"[2/7] Semantic verification ..... FAIL")
            return self._build_early_rejection(
                cand_id, syntax=syntax_res, semantic=semantic_res,
                rejection_reason=semantic_res.summary,
                duration=time.time() - start_time
            )
        notify("semantic", f"[2/7] Semantic verification ..... PASS")

        # ── Stage 3: Test Verification ────────────────────────
        notify("testing", f"[3/7] Test verification ......... RUNNING")
        test_res = self.test_verifier.verify(
            candidate_id=cand_id,
            original_code=original_code,
            candidate_code=candidate_code,
            test_code=test_code,
            test_command=test_command,
            original_test_result=original_test_result,
        )
        if not test_res.passed:
            notify("testing", f"[3/7] Test verification ......... FAIL")
            return self._build_early_rejection(
                cand_id, syntax=syntax_res, semantic=semantic_res, tests=test_res,
                rejection_reason=test_res.details,
                duration=time.time() - start_time
            )
        notify("testing", f"[3/7] Test verification ......... PASS")

        # ── Stage 4: Runtime Verification ─────────────────────
        notify("runtime", f"[4/7] Runtime verification ...... RUNNING")
        runtime_res = self.runtime_verifier.verify(candidate_code)
        if not runtime_res.passed:
            notify("runtime", f"[4/7] Runtime verification ...... FAIL")
            return self._build_early_rejection(
                cand_id, syntax=syntax_res, semantic=semantic_res, tests=test_res,
                runtime=runtime_res,
                rejection_reason=f"Runtime exception: {runtime_res.error_message}",
                duration=time.time() - start_time
            )
        notify("runtime", f"[4/7] Runtime verification ...... PASS")

        # ── Stage 5: Differential & Edge-Case Testing ─────────
        notify("differential", f"  › Running differential & adversarial edge-case testing")
        diff_res = self.differential_tester.verify(
            original_code=original_code,
            candidate_code=candidate_code,
        )
        if diff_res.has_regression:
            notify("regression", f"[6/7] Regression analysis ....... FAIL")
            discrepancy = diff_res.discrepancies[0]
            reason = (
                f"Differential regression on input {discrepancy.get('input')}: "
                f"expected {discrepancy.get('original_output')}, got {discrepancy.get('candidate_output')}"
            )
            return self._build_early_rejection(
                cand_id, syntax=syntax_res, semantic=semantic_res, tests=test_res,
                runtime=runtime_res, differential=diff_res,
                rejection_reason=reason,
                duration=time.time() - start_time
            )

        # ── Stage 6: Complexity Analysis ──────────────────────
        notify("complexity", f"[7/7] Complexity analysis ....... RUNNING")
        complexity_res = self.complexity_verifier.verify(
            original_analysis=original_analysis,
            candidate_analysis=candidate_analysis,
        )
        notify("complexity", f"[7/7] Complexity analysis ....... {complexity_res.status}")

        # ── Stage 7: Gemma 4 Logical Verification ─────────────
        notify("logical", f"[5/7] Logical verification ...... RUNNING")
        logic_res = self.logical_verifier.verify(
            original_code=original_code,
            candidate_code=candidate_code,
            diff=diff_text,
            tests=test_code or "Standard sanity suite",
            test_results=f"Passed {test_res.candidate_tests.get('passed', 0)} tests",
            static_analysis=semantic_res.summary,
            runtime_results=f"Exit code {runtime_res.exit_code}",
            complexity_results=f"Time {complexity_res.time_before} → {complexity_res.time_after}",
        )
        notify("logical", f"[5/7] Logical verification ...... {logic_res.verdict.value}")

        notify("regression", f"[6/7] Regression analysis ....... PASS")

        # ── Stage 8: Composite Verdict Evaluation ─────────────
        final_verdict, score, rejections, reviews = self.verdict_evaluator.evaluate(
            syntax=syntax_res,
            semantic=semantic_res,
            tests=test_res,
            runtime=runtime_res,
            differential=diff_res,
            logic=logic_res,
            complexity=complexity_res,
        )

        # Compute mutation analysis metadata
        mutation_analysis = self._build_mutation_analysis(
            candidate=candidate,
            diff_text=diff_text,
            verdict=final_verdict,
        )

        return VerificationReport(
            candidate_id=cand_id,
            syntax=syntax_res,
            semantic=semantic_res,
            tests=test_res,
            runtime=runtime_res,
            differential=diff_res,
            logic=logic_res,
            regression=CheckStatus.PASS if not diff_res.has_regression and not test_res.has_regression else CheckStatus.FAIL,
            complexity=complexity_res,
            mutation_analysis=mutation_analysis,
            verification_score=score,
            final_verdict=final_verdict,
            rejection_reasons=rejections,
            review_reasons=reviews,
            duration_seconds=time.time() - start_time,
        )

    def _build_early_rejection(
        self,
        candidate_id: str,
        syntax: Optional[SyntaxCheckResult] = None,
        semantic: Optional[SemanticCheckResult] = None,
        tests: Optional[TestCheckResult] = None,
        runtime: Optional[RuntimeCheckResult] = None,
        differential: Optional[DifferentialResult] = None,
        rejection_reason: str = "",
        duration: float = 0.0,
    ) -> VerificationReport:
        """Construct an early failure report when deterministic verification gates fail."""
        return VerificationReport(
            candidate_id=candidate_id,
            syntax=syntax or SyntaxCheckResult(),
            semantic=semantic or SemanticCheckResult(),
            tests=tests or TestCheckResult(),
            runtime=runtime or RuntimeCheckResult(),
            differential=differential or DifferentialResult(),
            logic=LogicalAnalysisResult(
                verdict=CheckStatus.FAIL,
                confidence=1.0,
                logical_correctness={"status": "FAIL", "reason": rejection_reason},
                behavior_preservation={"status": "FAIL", "reason": rejection_reason},
                recommendation=VerificationVerdict.REJECT,
            ),
            regression=CheckStatus.FAIL if (differential and differential.has_regression) or (tests and tests.has_regression) else CheckStatus.PASS,
            complexity=ComplexityCheckResult(),
            verification_score=0.0,
            final_verdict=VerificationVerdict.REJECT,
            rejection_reasons=[rejection_reason] if rejection_reason else ["Deterministic check failed"],
            review_reasons=[],
            duration_seconds=duration,
        )

    def _build_mutation_analysis(
        self,
        candidate: MutationCandidate,
        diff_text: str,
        verdict: VerificationVerdict,
    ) -> MutationAnalysis:
        """Extract metadata about lines changed and affected functions."""
        changed_lines = []
        affected_functions = []

        if diff_text:
            for line in diff_text.splitlines():
                if line.startswith("@@"):
                    # Example: @@ -10,5 +10,6 @@
                    try:
                        part = line.split("+")[1].split(" ")[0].split(",")[0]
                        changed_lines.append(int(part))
                    except Exception:
                        pass
                elif line.startswith("+def ") or line.startswith("-def "):
                    fn_name = line.split("def ")[1].split("(")[0].strip()
                    if fn_name not in affected_functions:
                        affected_functions.append(fn_name)

        strat_str = candidate.strategy.value if hasattr(candidate.strategy, "value") else str(candidate.strategy)
        risk = "HIGH" if verdict == VerificationVerdict.REJECT else "LOW" if verdict == VerificationVerdict.ACCEPT else "MEDIUM"

        return MutationAnalysis(
            mutation_id=candidate.candidate_id,
            mutation_type=strat_str,
            changed_lines=changed_lines,
            affected_functions=affected_functions,
            behavioral_risk=risk,
            verification=verdict.value,
        )
