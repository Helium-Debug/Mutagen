"""
Automated test runner for MUTAGEN.

Runs correctness tests against candidate implementations inside
the isolated sandbox. Never executes untrusted code on the host.
"""

from __future__ import annotations

import json
from typing import Optional

from mutagen.core.logging import get_logger
from mutagen.sandbox.docker_manager import DockerSandbox
from mutagen.schemas import TestResult

logger = get_logger("testing")


class TestRunner:
    """
    Runs automated tests against code candidates in the sandbox.

    Supports:
    - Custom test commands
    - Inline test code
    - pytest (for Python candidates)
    - Timeout detection
    - Structured result parsing
    """

    def __init__(
        self,
        sandbox: DockerSandbox,
        timeout: int = 30,
    ):
        self.sandbox = sandbox
        self.timeout = timeout

    def run_tests(
        self,
        candidate_id: str,
        code: str,
        test_code: Optional[str] = None,
        test_command: Optional[str] = None,
    ) -> TestResult:
        """
        Run tests against a candidate implementation.

        Args:
            candidate_id: The candidate being tested.
            code: The candidate source code.
            test_code: Inline test code to run against the candidate.
            test_command: Shell command to run tests (used in sandbox).

        Returns:
            TestResult with pass/fail details.
        """
        if test_code:
            return self._run_inline_tests(candidate_id, code, test_code)
        else:
            return self._run_basic_validation(candidate_id, code)

    def _run_inline_tests(
        self,
        candidate_id: str,
        code: str,
        test_code: str,
    ) -> TestResult:
        """Run inline test code against the candidate in the sandbox."""
        result = self.sandbox.execute_python(
            code=code,
            test_code=test_code,
            timeout=self.timeout,
        )

        test_result = TestResult(
            candidate_id=candidate_id,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            timed_out=result.timed_out,
            output=result.stdout[:5000],
        )

        if result.timed_out:
            test_result.failure_summaries.append("Test execution timed out")
            return test_result

        if result.success:
            # Try to parse structured results from stdout
            self._parse_test_output(test_result, result.stdout)
            if test_result.total_tests == 0:
                test_result.total_tests = 1
                test_result.passed = 1
        else:
            test_result.failed = 1
            test_result.total_tests = 1
            if result.stderr:
                test_result.failure_summaries.append(result.stderr[:2000])
            if result.error:
                test_result.failure_summaries.append(result.error)

        return test_result

    def _run_basic_validation(
        self,
        candidate_id: str,
        code: str,
    ) -> TestResult:
        """Run basic execution validation (can the code run without errors?)."""
        result = self.sandbox.execute_python(
            code=code,
            timeout=self.timeout,
        )

        test_result = TestResult(
            candidate_id=candidate_id,
            total_tests=1,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            timed_out=result.timed_out,
            output=result.stdout[:5000],
        )

        if result.success:
            test_result.passed = 1
        else:
            test_result.failed = 1
            if result.stderr:
                test_result.failure_summaries.append(result.stderr[:2000])
            if result.error:
                test_result.failure_summaries.append(result.error)
            try:
                start_idx = result.stdout.find("{")
                end_idx = result.stdout.rfind("}")
                if start_idx != -1 and end_idx != -1:
                    data = json.loads(result.stdout[start_idx:end_idx + 1])
                    if data.get("errors"):
                        test_result.failure_summaries.append(data["errors"][:2000])
            except Exception:
                pass

        return test_result

    def _parse_test_output(self, test_result: TestResult, stdout: str) -> None:
        """Try to parse structured test results from stdout."""
        try:
            # Look for JSON test results
            for line in stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    data = json.loads(line)
                    if "tests" in data or "total_tests" in data:
                        test_result.total_tests = data.get("total_tests", data.get("tests", 0))
                        test_result.passed = data.get("passed", 0)
                        test_result.failed = data.get("failed", 0)
                        test_result.skipped = data.get("skipped", 0)
                        return
        except (json.JSONDecodeError, ValueError):
            pass
