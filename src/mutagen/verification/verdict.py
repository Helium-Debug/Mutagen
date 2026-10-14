"""
Verdict & Scoring System for MUTAGEN Verification.

Applies strict correctness-first prioritization. Performance improvements
never compensate for logical or runtime incorrectness. Evaluates deterministic
and probabilistic signals into a final verdict: ACCEPT, REJECT, or REVIEW.
"""

from __future__ import annotations

from typing import Optional

from mutagen.verification.schemas import (
    CheckStatus, ComplexityCheckResult, DifferentialResult,
    LogicalAnalysisResult, RuntimeCheckResult, SemanticCheckResult,
    Severity, SyntaxCheckResult, TestCheckResult, VerificationVerdict,
)


class VerdictEvaluator:
    """Evaluates composite verification results into a final verdict and correctness score."""

    def evaluate(
        self,
        syntax: SyntaxCheckResult,
        semantic: SemanticCheckResult,
        tests: TestCheckResult,
        runtime: RuntimeCheckResult,
        differential: DifferentialResult,
        logic: LogicalAnalysisResult,
        complexity: ComplexityCheckResult,
    ) -> tuple[VerificationVerdict, float, list[str], list[str]]:
        """
        Determine the final verdict and correctness score.

        Returns:
            Tuple of:
            - verdict (ACCEPT | REJECT | REVIEW)
            - verification_score (0.0 to 1.0)
            - rejection_reasons (list[str])
            - review_reasons (list[str])
        """
        rejection_reasons: list[str] = []
        review_reasons: list[str] = []

        # ── 1. Deterministic Hard Gates (Immediate REJECT on failure) ──
        # Syntax Check
        if not syntax.passed:
            rejection_reasons.append(
                f"Syntax verification failed: {syntax.message or 'Malformed syntax'} "
                f"(Line {syntax.line or 1}, Column {syntax.column or 1})"
            )

        # Semantic Check (Critical or High severity issues)
        if not semantic.passed:
            crit_errors = [
                d.message for d in semantic.diagnostics
                if d.severity in (Severity.CRITICAL.value, Severity.HIGH.value)
            ]
            rejection_reasons.append(
                f"Semantic verification failed: {'; '.join(crit_errors) if crit_errors else semantic.summary}"
            )

        # Test Regression
        if not tests.passed:
            rejection_reasons.append(f"Test verification failed: {tests.details}")

        # Runtime Check
        if not runtime.passed:
            err = runtime.error_message or "Execution failed"
            rejection_reasons.append(f"Runtime execution failed: {err}")

        # Differential Regression (Output discrepancy detected)
        if differential.has_regression:
            discrepancy = differential.discrepancies[0]
            func_name = discrepancy.get("function", "module")
            inp = discrepancy.get("input", "")
            orig_out = discrepancy.get("original_output", "")
            cand_out = discrepancy.get("candidate_output", "")
            rejection_reasons.append(
                f"Behavioral regression detected via differential testing in '{func_name}' "
                f"for input {inp}: expected {orig_out}, got {cand_out}"
            )

        # ── 2. Logical Reasoning Evaluation (Gemma 4) ──
        if logic.verdict == CheckStatus.FAIL:
            if logic.confidence >= 0.70:
                reason = logic.logical_correctness.get("reason") or logic.behavior_preservation.get("reason") or "Logical error detected"
                rejection_reasons.append(
                    f"Logical verification failed ({int(logic.confidence * 100)}% confidence): {reason}"
                )
            else:
                review_reasons.append(
                    f"Low-confidence logical concern ({int(logic.confidence * 100)}% confidence)"
                )
        elif logic.verdict == CheckStatus.UNCERTAIN or logic.recommendation == VerificationVerdict.REVIEW:
            review_reasons.append(
                f"Logical verification inconclusive (confidence: {int(logic.confidence * 100)}%)"
            )
        elif logic.verdict == CheckStatus.UNAVAILABLE:
            review_reasons.append("Logical verification reasoning unavailable (AI service offline)")

        # High risk edge cases detected by model
        high_risk_edges = [e for e in logic.edge_cases if e.get("risk", "").upper() == "HIGH"]
        if high_risk_edges:
            review_reasons.append(
                f"High-risk edge case detected: {high_risk_edges[0].get('case', 'Unknown boundary condition')}"
            )

        # Complexity Regressions
        if complexity.time_regression:
            review_reasons.append(
                f"Time complexity degraded: {complexity.time_before} → {complexity.time_after}"
            )
        if complexity.space_regression:
            review_reasons.append(
                f"Space complexity degraded: {complexity.space_before} → {complexity.space_after}"
            )

        # ── 3. Correctness Score Calculation ──
        # Component weights:
        # Syntax: 25%, Semantic: 20%, Tests: 20%, Runtime: 15%, Differential: 10%, Logic: 10%
        score = 0.0
        if syntax.passed:
            score += 0.25
        if semantic.passed:
            score += 0.20
        if tests.passed:
            score += 0.20
        if runtime.passed:
            score += 0.15
        if not differential.has_regression:
            score += 0.10

        if logic.verdict == CheckStatus.PASS:
            score += 0.10 * max(0.5, logic.confidence)
        elif logic.verdict == CheckStatus.UNCERTAIN:
            score += 0.05
        elif logic.verdict == CheckStatus.UNAVAILABLE:
            score += 0.05

        score = round(max(0.0, min(1.0, score)), 3)

        # ── 4. Final Verdict Determination ──
        if rejection_reasons:
            final_verdict = VerificationVerdict.REJECT
            score = 0.0
        elif review_reasons:
            final_verdict = VerificationVerdict.REVIEW
        else:
            final_verdict = VerificationVerdict.ACCEPT

        return final_verdict, score, rejection_reasons, review_reasons
