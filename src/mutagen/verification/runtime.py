"""
Runtime Verification Stage for MUTAGEN.

Executes candidate code inside the secure sandbox environment to detect
unhandled runtime exceptions, timeouts, memory violations, and crash dumps.
"""

from __future__ import annotations

import json
from typing import Optional

from mutagen.sandbox.docker_manager import DockerSandbox, SandboxResult
from mutagen.verification.schemas import CheckStatus, RuntimeCheckResult


class RuntimeVerifier:
    """Verifies that code runs to completion safely without runtime faults."""

    def __init__(self, sandbox: DockerSandbox, timeout: int = 15):
        self.sandbox = sandbox
        self.timeout = timeout

    def verify(
        self,
        candidate_code: str,
        timeout: Optional[int] = None,
    ) -> RuntimeCheckResult:
        """
        Execute candidate code in the sandbox to verify runtime stability.

        Returns:
            RuntimeCheckResult with exit code, timeout status, and stack traces if crashed.
        """
        run_timeout = timeout or self.timeout
        result: SandboxResult = self.sandbox.execute_python(
            code=candidate_code,
            timeout=run_timeout,
        )

        if result.timed_out:
            return RuntimeCheckResult(
                status=CheckStatus.FAIL,
                exit_code=-1,
                timed_out=True,
                error_message=f"Runtime execution timed out after {run_timeout} seconds (potential infinite loop)",
            )

        if not result.success:
            err_msg = result.error or (result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Runtime execution failed")
            tb = result.stderr

            # Try to extract detailed error from structured sandbox JSON if available
            try:
                start_idx = result.stdout.find("{")
                end_idx = result.stdout.rfind("}")
                if start_idx != -1 and end_idx != -1:
                    data = json.loads(result.stdout[start_idx:end_idx + 1])
                    if data.get("errors"):
                        tb = data["errors"]
                        err_msg = tb.splitlines()[-1] if tb.splitlines() else err_msg
            except Exception:
                pass

            return RuntimeCheckResult(
                status=CheckStatus.FAIL,
                exit_code=result.exit_code,
                timed_out=False,
                error_message=err_msg,
                traceback=tb,
            )

        return RuntimeCheckResult(
            status=CheckStatus.PASS,
            exit_code=0,
            timed_out=False,
            error_message=None,
            traceback=None,
        )
