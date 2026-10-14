"""
Test Verification Stage for MUTAGEN.

Executes existing unit/integration tests against both the original code
and the mutation candidate. Ensures zero test regressions.
"""

from __future__ import annotations

from typing import Optional

from mutagen.schemas import TestResult
from mutagen.testing.test_runner import TestRunner
from mutagen.verification.schemas import CheckStatus, TestCheckResult


class TestVerifier:
    """Verifies that mutation candidates do not cause test regressions."""

    __test__ = False

    def __init__(self, test_runner: Optional[TestRunner] = None):
        self.test_runner = test_runner or TestRunner()

    def verify(
        self,
        candidate_id: str,
        original_code: str,
        candidate_code: str,
        test_code: Optional[str] = None,
        test_command: Optional[str] = None,
        original_test_result: Optional[TestResult] = None,
    ) -> TestCheckResult:
        """
        Compare original test execution results against candidate test execution results.

        Returns:
            TestCheckResult tracking pass/fail stats and regression flags.
        """
        # Run original tests if not already provided
        if original_test_result is None:
            try:
                original_test_result = self.test_runner.run_tests(
                    candidate_id="original",
                    code=original_code,
                    test_code=test_code,
                    test_command=test_command,
                )
            except Exception as e:
                # If original code cannot be tested, default baseline
                original_test_result = TestResult(
                    candidate_id="original",
                    total_tests=0,
                    passed=0,
                    failed=0,
                )

        # Run candidate tests
        try:
            cand_test_result = self.test_runner.run_tests(
                candidate_id=candidate_id,
                code=candidate_code,
                test_code=test_code,
                test_command=test_command,
            )
        except Exception as e:
            return TestCheckResult(
                status=CheckStatus.FAIL,
                original_tests={
                    "passed": original_test_result.passed,
                    "failed": original_test_result.failed,
                },
                candidate_tests={"passed": 0, "failed": 1},
                has_regression=True,
                details=f"Candidate test execution crashed: {e}",
            )

        orig_stats = {
            "passed": original_test_result.passed,
            "failed": original_test_result.failed,
        }
        cand_stats = {
            "passed": cand_test_result.passed,
            "failed": cand_test_result.failed,
        }

        # Check for regression:
        # 1. Candidate tests failed while original tests passed
        # 2. Candidate tests failed count > original tests failed count
        # 3. Candidate execution failed/timed out
        has_regression = False
        details = "Test suite passed cleanly."

        if not cand_test_result.all_passed:
            if original_test_result.all_passed:
                has_regression = True
                fail_summary = (
                    cand_test_result.failure_summaries[0]
                    if cand_test_result.failure_summaries
                    else f"Exit code {cand_test_result.exit_code}"
                )
                details = f"Test regression detected: {cand_test_result.failed} test(s) failed ({fail_summary})"
            elif cand_test_result.failed > original_test_result.failed:
                has_regression = True
                details = (
                    f"Test regression detected: failure count increased from "
                    f"{original_test_result.failed} to {cand_test_result.failed}."
                )
            else:
                details = f"Tests failed: {cand_test_result.failed} failures (baseline had {original_test_result.failed})."

        status = CheckStatus.FAIL if has_regression or (cand_test_result.failed > 0 and original_test_result.failed == 0) else CheckStatus.PASS

        return TestCheckResult(
            status=status,
            original_tests=orig_stats,
            candidate_tests=cand_stats,
            has_regression=has_regression,
            details=details,
        )
