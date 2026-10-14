"""
Syntax Verification Stage for MUTAGEN.

Performs language-aware syntax parsing and compilation checks.
Rejects malformed code early before any expensive testing or LLM reasoning.
"""

from __future__ import annotations

import ast
from typing import Optional

from mutagen.schemas import ProgrammingLanguage
from mutagen.verification.schemas import (
    CheckStatus, Severity, SyntaxCheckResult,
)


class SyntaxVerifier:
    """Verifies that code parses cleanly and has no malformed syntax."""

    def verify(
        self,
        source_code: str,
        language: str = "python",
        file_path: Optional[str] = None,
    ) -> SyntaxCheckResult:
        """
        Verify the syntax of candidate source code.

        Returns:
            SyntaxCheckResult with exact line, column, and message if failed.
        """
        lang = language.lower() if isinstance(language, str) else language.value.lower()

        if lang in ("python", "py"):
            return self._verify_python(source_code, file_path or "<candidate>")
        else:
            # Basic fallback for other languages (ensures non-empty and basic balanced brackets)
            return self._verify_generic(source_code)

    def _verify_python(self, source_code: str, filename: str) -> SyntaxCheckResult:
        if not source_code or not source_code.strip():
            return SyntaxCheckResult(
                category="syntax",
                status=CheckStatus.FAIL,
                severity=Severity.CRITICAL,
                line=1,
                column=1,
                message="Source code is empty.",
            )

        try:
            # Step 1: AST parsing
            ast.parse(source_code, filename=filename)

            # Step 2: Bytecode compilation check
            compile(source_code, filename, "exec")

            return SyntaxCheckResult(
                category="syntax",
                status=CheckStatus.PASS,
                severity=None,
                message=None,
            )
        except SyntaxError as e:
            return SyntaxCheckResult(
                category="syntax",
                status=CheckStatus.FAIL,
                severity=Severity.CRITICAL,
                line=e.lineno or 1,
                column=e.offset or 1,
                message=f"Syntax error: {e.msg}" if e.msg else "Malformed syntax",
            )
        except Exception as e:
            return SyntaxCheckResult(
                category="syntax",
                status=CheckStatus.FAIL,
                severity=Severity.CRITICAL,
                line=1,
                column=1,
                message=f"Parser failure: {e}",
            )

    def _verify_generic(self, source_code: str) -> SyntaxCheckResult:
        if not source_code or not source_code.strip():
            return SyntaxCheckResult(
                category="syntax",
                status=CheckStatus.FAIL,
                severity=Severity.CRITICAL,
                line=1,
                column=1,
                message="Source code is empty.",
            )

        # Basic balanced braces check
        stack = []
        pairs = {')': '(', '}': '{', ']': '['}
        lines = source_code.splitlines()

        for line_num, line in enumerate(lines, start=1):
            for col_num, char in enumerate(line, start=1):
                if char in "({[":
                    stack.append((char, line_num, col_num))
                elif char in ")}]":
                    if not stack or stack[-1][0] != pairs[char]:
                        return SyntaxCheckResult(
                            category="syntax",
                            status=CheckStatus.FAIL,
                            severity=Severity.CRITICAL,
                            line=line_num,
                            column=col_num,
                            message=f"Unmatched closing delimiter '{char}'",
                        )
                    stack.pop()

        if stack:
            unmatched, line_num, col_num = stack[-1]
            return SyntaxCheckResult(
                category="syntax",
                status=CheckStatus.FAIL,
                severity=Severity.CRITICAL,
                line=line_num,
                column=col_num,
                message=f"Unclosed delimiter '{unmatched}'",
            )

        return SyntaxCheckResult(category="syntax", status=CheckStatus.PASS)
