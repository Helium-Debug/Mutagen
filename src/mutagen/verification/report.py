"""
Verification Reporting & Formatting Utilities for MUTAGEN.

Provides formatted terminal reports (both stage-by-stage progress and full
composite reports) and machine-readable JSON serializations.
"""

from __future__ import annotations

from typing import Any

from mutagen.verification.schemas import (
    CheckStatus, VerificationReport, VerificationVerdict,
)


def format_terminal_stages(report: VerificationReport) -> list[str]:
    """
    Format the 7 verification stages for terminal display as per Section 15.
    """
    lines = []

    # 1/7 Syntax
    syn_status = "PASS" if report.syntax.passed else "FAIL"
    lines.append(f"[1/7] Syntax verification ........ {syn_status}")

    # 2/7 Semantic
    sem_status = "PASS" if report.semantic.passed else "FAIL"
    lines.append(f"[2/7] Semantic verification ..... {sem_status}")

    # 3/7 Tests
    t_status = "PASS" if report.tests.passed else "FAIL"
    lines.append(f"[3/7] Test verification ......... {t_status}")

    # 4/7 Runtime
    rt_status = "PASS" if report.runtime.passed else "FAIL"
    lines.append(f"[4/7] Runtime verification ...... {rt_status}")

    # 5/7 Logical
    log_status = report.logic.verdict.value if isinstance(report.logic.verdict, CheckStatus) else str(report.logic.verdict)
    lines.append(f"[5/7] Logical verification ...... {log_status}")

    # 6/7 Regression
    reg_status = "PASS" if (not report.differential.has_regression and not report.tests.has_regression) else "FAIL"
    lines.append(f"[6/7] Regression analysis ....... {reg_status}")

    # 7/7 Complexity
    comp_status = report.complexity.status
    lines.append(f"[7/7] Complexity analysis ....... {comp_status}")

    return lines


def format_verification_report(report: VerificationReport | dict[str, Any]) -> str:
    """
    Format the complete verification report as specified in Section 14.
    """
    if isinstance(report, dict):
        report = VerificationReport.model_validate(report)
    sep = "═" * 44
    div = "─" * 44

    lines = [
        sep,
        " MUTAGEN VERIFICATION REPORT",
        sep,
        "",
        f"Candidate: {report.candidate_id}",
        "",
        "SYNTAX",
        f"{'✓ PASS' if report.syntax.passed else '✗ FAIL'}",
        *( [f"  Line {report.syntax.line}: {report.syntax.message}"] if not report.syntax.passed else [] ),
        "",
        "SEMANTIC",
        f"{'✓ PASS' if report.semantic.passed else '✗ FAIL'}",
        *( [f"  {d.message}" for d in report.semantic.diagnostics[:2]] if not report.semantic.passed else [] ),
        "",
        "TESTS",
        f"{'✓' if report.tests.passed else '✗'} {report.tests.candidate_tests.get('passed', 0)} / {report.tests.candidate_tests.get('passed', 0) + report.tests.candidate_tests.get('failed', 0)} PASS",
        *( [f"  {report.tests.details}"] if not report.tests.passed else [] ),
        "",
        "RUNTIME",
        f"{'✓ PASS' if report.runtime.passed else '✗ FAIL'}",
        *( [f"  {report.runtime.error_message}"] if not report.runtime.passed else [] ),
        "",
        "LOGICAL ANALYSIS",
        f"{'✓ PASS' if report.logic.verdict == CheckStatus.PASS else '✗ ' + str(report.logic.verdict.value)}",
        f"Confidence: {report.logic.confidence:.2f}",
        *( [f"  {report.logic.logical_correctness.get('reason', '')}"] if report.logic.logical_correctness.get('reason') else [] ),
        "",
        "REGRESSION",
        f"{'✓ NONE DETECTED' if not report.differential.has_regression and not report.tests.has_regression else '✗ REGRESSION DETECTED'}",
        *( [f"  {d.get('input')}: {d.get('original_output')} != {d.get('candidate_output')}" for d in report.differential.discrepancies[:2]] if report.differential.has_regression else [] ),
        "",
        "TIME COMPLEXITY",
        f"{'✓' if not report.complexity.time_regression else '✗'} {report.complexity.time_before} → {report.complexity.time_after}",
        "",
        "SPACE COMPLEXITY",
        f"{'✓' if not report.complexity.space_regression else '✗'} {report.complexity.space_before} → {report.complexity.space_after}",
        "",
        div,
        "",
        f"FINAL VERDICT: {report.final_verdict.value}",
        "",
    ]

    if report.final_verdict == VerificationVerdict.ACCEPT:
        lines.append(f"Performance improvement: {report.performance_improvement_percent:+.1f}%")
        lines.append("Correctness preserved: YES")
    elif report.final_verdict == VerificationVerdict.REJECT:
        lines.append("Reason:")
        for r in report.rejection_reasons[:3]:
            lines.append(f"  • {r}")
        lines.append("")
        lines.append("Detected by:")
        detectors = []
        if not report.syntax.passed:
            detectors.append("Syntax Analyzer")
        if not report.semantic.passed:
            detectors.append("Semantic Static Analyzer")
        if not report.tests.passed:
            detectors.append("Test Runner")
        if not report.runtime.passed:
            detectors.append("Sandbox Runtime")
        if report.differential.has_regression:
            detectors.append("Differential Testing")
        if report.logic.verdict == CheckStatus.FAIL:
            detectors.append("Gemma 4 Analysis")
        lines.append(f"  { ' + '.join(detectors) if detectors else 'Verification System' }")
    else:  # REVIEW
        lines.append("Review Notes:")
        for r in report.review_reasons[:3]:
            lines.append(f"  • {r}")

    lines.append(sep)
    return "\n".join(lines)


def to_machine_dict(report: VerificationReport) -> dict[str, Any]:
    """
    Produce machine-readable JSON matching Section 16 format.
    """
    total_tests = report.tests.candidate_tests.get("passed", 0) + report.tests.candidate_tests.get("failed", 0)
    return {
        "candidate_id": report.candidate_id,
        "syntax": {
            "status": "PASS" if report.syntax.passed else "FAIL",
            "line": report.syntax.line,
            "column": report.syntax.column,
            "message": report.syntax.message,
        },
        "semantic": {
            "status": "PASS" if report.semantic.passed else "FAIL",
            "diagnostics": [d.model_dump() for d in report.semantic.diagnostics],
        },
        "tests": {
            "status": "PASS" if report.tests.passed else "FAIL",
            "passed": report.tests.candidate_tests.get("passed", 0),
            "failed": report.tests.candidate_tests.get("failed", 0),
            "total": total_tests,
        },
        "runtime": {
            "status": "PASS" if report.runtime.passed else "FAIL",
            "exit_code": report.runtime.exit_code,
            "timed_out": report.runtime.timed_out,
            "error": report.runtime.error_message,
        },
        "differential": {
            "status": "PASS" if not report.differential.has_regression else "FAIL",
            "inputs_tested": report.differential.inputs_tested,
            "discrepancies": report.differential.discrepancies,
        },
        "logic": {
            "status": report.logic.verdict.value,
            "confidence": report.logic.confidence,
            "logical_correctness": report.logic.logical_correctness,
            "behavior_preservation": report.logic.behavior_preservation,
            "edge_cases": report.logic.edge_cases,
            "detected_errors": report.logic.detected_errors,
            "suggested_tests": report.logic.suggested_tests,
            "recommendation": report.logic.recommendation.value,
        },
        "regression": {
            "status": "PASS" if not report.differential.has_regression and not report.tests.has_regression else "FAIL",
        },
        "complexity": {
            "status": report.complexity.status,
            "time": {
                "before": report.complexity.time_before,
                "after": report.complexity.time_after,
            },
            "space": {
                "before": report.complexity.space_before,
                "after": report.complexity.space_after,
            },
        },
        "verification_score": report.verification_score,
        "final_verdict": report.final_verdict.value,
        "rejection_reasons": report.rejection_reasons,
        "review_reasons": report.review_reasons,
    }
