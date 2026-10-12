"""
Diff engine and source inspection service for MUTAGEN.

Calculates programmatic unified diffs, detects modified functions using AST,
computes line and file change statistics, generates candidate evolution reports,
and exports patches.
"""

from __future__ import annotations

import ast
import difflib
from pathlib import Path
from typing import Optional

from mutagen.core.security import compute_content_hash
from mutagen.exceptions import MutagenValidationError
from mutagen.schemas import CandidateDiffReport, DiffSummary


class DiffService:
    """Service for computing, analyzing, and formatting source code diffs."""

    @staticmethod
    def compute_unified_diff(
        original: str,
        candidate: str,
        fromfile: str = "Original",
        tofile: str = "Optimized",
        context: int = 3,
    ) -> str:
        """
        Generate a unified diff between two code strings.

        Args:
            original: Original source code.
            candidate: Candidate source code.
            fromfile: Label for the original version.
            tofile: Label for the modified version.
            context: Number of context lines around changes.

        Returns:
            Unified diff text.
        """
        orig_lines = original.splitlines(keepends=True)
        cand_lines = candidate.splitlines(keepends=True)

        # Ensure trailing newline consistency
        if orig_lines and not orig_lines[-1].endswith("\n"):
            orig_lines[-1] = orig_lines[-1] + "\n"
        if cand_lines and not cand_lines[-1].endswith("\n"):
            cand_lines[-1] = cand_lines[-1] + "\n"

        diff_gen = difflib.unified_diff(
            orig_lines,
            cand_lines,
            fromfile=fromfile,
            tofile=tofile,
            n=context,
            lineterm="",
        )
        return "".join(diff_gen)

    @staticmethod
    def summarize_changes(
        original: str,
        candidate: str,
        file_path: str = "",
    ) -> DiffSummary:
        """
        Calculate statistics for code changes: lines added, lines removed,
        and functions modified (for Python code).
        """
        orig_lines = original.splitlines()
        cand_lines = candidate.splitlines()

        matcher = difflib.SequenceMatcher(None, orig_lines, cand_lines)
        lines_added = 0
        lines_removed = 0

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "replace":
                lines_removed += (i2 - i1)
                lines_added += (j2 - j1)
            elif tag == "delete":
                lines_removed += (i2 - i1)
            elif tag == "insert":
                lines_added += (j2 - j1)

        # Detect function-level modifications for Python
        modified_functions = []
        try:
            orig_ast = ast.parse(original)
            cand_ast = ast.parse(candidate)

            orig_funcs = {
                node.name: ast.dump(node)
                for node in ast.walk(orig_ast)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            cand_funcs = {
                node.name: ast.dump(node)
                for node in ast.walk(cand_ast)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }

            for name, dump_orig in orig_funcs.items():
                if name in cand_funcs:
                    if dump_orig != cand_funcs[name]:
                        modified_functions.append(name)
                else:
                    modified_functions.append(f"{name} (removed)")

            for name in cand_funcs:
                if name not in orig_funcs:
                    modified_functions.append(f"{name} (added)")

        except Exception:
            # If parsing fails or non-Python code, function diffs are skipped
            pass

        return DiffSummary(
            file_path=file_path,
            files_changed=1 if original != candidate else 0,
            lines_added=lines_added,
            lines_removed=lines_removed,
            functions_modified=len(modified_functions),
            modified_functions=modified_functions,
        )

    @classmethod
    def create_candidate_report(
        cls,
        experiment_id: str,
        candidate_id: str,
        original_code: str,
        candidate_code: str,
        file_path: str = "",
        generation: int = 1,
        strategy: str = "general",
        status: str = "valid",
        validation_passed: bool = False,
        tests_passed: bool = False,
        baseline_median_time: Optional[float] = None,
        candidate_median_time: Optional[float] = None,
        speed_improvement_percent: Optional[float] = None,
        memory_improvement_percent: Optional[float] = None,
        fitness_score: Optional[float] = None,
        is_eligible: bool = False,
        rejection_reason: Optional[str] = None,
        context: int = 3,
    ) -> CandidateDiffReport:
        """Construct a complete CandidateDiffReport from candidate execution data."""
        diff_text = cls.compute_unified_diff(
            original=original_code,
            candidate=candidate_code,
            fromfile=f"a/{file_path or 'original'}",
            tofile=f"b/{file_path or 'optimized'}",
            context=context,
        )
        summary = cls.summarize_changes(
            original=original_code,
            candidate=candidate_code,
            file_path=file_path,
        )

        return CandidateDiffReport(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            generation=generation,
            strategy=strategy,
            status=status,
            file_path=file_path,
            original_code=original_code,
            candidate_code=candidate_code,
            diff_text=diff_text,
            summary=summary,
            validation_passed=validation_passed,
            tests_passed=tests_passed,
            baseline_median_time=baseline_median_time,
            candidate_median_time=candidate_median_time,
            speed_improvement_percent=speed_improvement_percent,
            memory_improvement_percent=memory_improvement_percent,
            fitness_score=fitness_score,
            is_eligible=is_eligible,
            rejection_reason=rejection_reason,
        )

    @staticmethod
    def export_patch_file(diff_text: str, output_path: str | Path) -> Path:
        """Write a unified diff string to a patch file."""
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(diff_text, encoding="utf-8")
        return out

    @staticmethod
    def check_file_conflict(file_path: str | Path, expected_hash: str) -> tuple[bool, Optional[str]]:
        """
        Check if the file on disk has changed from the expected source hash.

        Returns:
            (has_conflict, current_content)
        """
        path = Path(file_path).resolve()
        if not path.exists():
            return True, None
        content = path.read_text(encoding="utf-8")
        current_hash = compute_content_hash(content)
        return current_hash != expected_hash, content
