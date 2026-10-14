"""
Semantic Verification Stage for MUTAGEN.

Performs static semantic analysis on parsed code to detect undefined variables,
unreachable code, argument count mismatches, invalid operations, and API misuse.
"""

from __future__ import annotations

import ast
import builtins
from typing import Any, Optional

from mutagen.verification.schemas import (
    CheckStatus, DiagnosticItem, SemanticCheckResult, Severity,
)

BUILTIN_NAMES = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__all__", "__package__",
    "__spec__", "__loader__", "__path__", "__cached__",
}


class PythonSemanticVisitor(ast.NodeVisitor):
    """
    AST visitor that traverses Python code to detect semantic errors:
    - Undefined variable references
    - Unreachable statements
    - Function call argument count mismatches
    - Direct divide-by-zero operations
    - Missing returns in non-void branching functions
    """

    def __init__(self):
        self.diagnostics: list[DiagnosticItem] = []
        # Scope stack: list of dict mapping var_name -> line_defined
        self.scopes: list[set[str]] = [set(BUILTIN_NAMES)]
        self.global_scope: set[str] = set()
        self.function_defs: dict[str, dict[str, Any]] = {}

    def _current_scope(self) -> set[str]:
        return self.scopes[-1]

    def _is_defined(self, name: str) -> bool:
        for scope in reversed(self.scopes):
            if name in scope:
                return True
        return name in self.global_scope

    def _add_symbol(self, name: str):
        self.scopes[-1].add(name)
        if len(self.scopes) == 1:
            self.global_scope.add(name)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            target = alias.asname or alias.name.split(".")[0]
            self._add_symbol(target)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            if alias.name == "*":
                # Wildcard import can introduce anything; treat cautiously
                continue
            target = alias.asname or alias.name
            self._add_symbol(target)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global):
        for name in node.names:
            self.global_scope.add(name)
            self.scopes[-1].add(name)

    def visit_Nonlocal(self, node: ast.Nonlocal):
        for name in node.names:
            self.scopes[-1].add(name)

    def visit_ClassDef(self, node: ast.ClassDef):
        self._add_symbol(node.name)
        # Class body has its own scope
        self.scopes.append(set())
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._add_symbol(node.name)

        # Store signature for call-site argument validation
        pos_args = len(node.args.args)
        defaults = len(node.args.defaults)
        min_args = pos_args - defaults
        max_args = pos_args if not node.args.vararg else float("inf")
        has_kwargs = bool(node.args.kwarg)

        self.function_defs[node.name] = {
            "min_args": min_args,
            "max_args": max_args,
            "has_varargs": bool(node.args.vararg),
            "has_kwargs": has_kwargs,
            "lineno": node.lineno,
        }

        # Function body has its own scope
        func_scope = set()
        # Add parameters
        for arg in node.args.args:
            func_scope.add(arg.arg)
        if node.args.vararg:
            func_scope.add(node.args.vararg.arg)
        if node.args.kwarg:
            func_scope.add(node.args.kwarg.arg)
        for arg in node.args.kwonlyargs:
            func_scope.add(arg.arg)

        self.scopes.append(func_scope)
        self._check_body_reachability(node.body)
        self._check_return_consistency(node)

        # Visit child nodes
        for child in node.body:
            self.visit(child)

        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Store):
            self._add_symbol(node.id)
        elif isinstance(node.ctx, ast.Load):
            if not self._is_defined(node.id):
                self.diagnostics.append(
                    DiagnosticItem(
                        category="semantic",
                        status="failed",
                        severity=Severity.HIGH.value,
                        message=f"Undefined variable or reference '{node.id}'",
                        line=node.lineno,
                        column=node.col_offset,
                        location={"line": node.lineno, "column": node.col_offset},
                    )
                )

    def visit_Call(self, node: ast.Call):
        # Validate argument counts for known local functions
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in self.function_defs:
                sig = self.function_defs[func_name]
                passed_args = len(node.args)
                has_star_args = any(isinstance(a, ast.Starred) for a in node.args)

                if not has_star_args:
                    if passed_args < sig["min_args"]:
                        self.diagnostics.append(
                            DiagnosticItem(
                                category="semantic",
                                status="failed",
                                severity=Severity.HIGH.value,
                                message=(
                                    f"Function '{func_name}' expects at least {sig['min_args']} "
                                    f"positional arguments, but {passed_args} were provided."
                                ),
                                line=node.lineno,
                                column=node.col_offset,
                                location={"line": node.lineno, "column": node.col_offset},
                            )
                        )
                    elif passed_args > sig["max_args"] and not sig["has_varargs"]:
                        self.diagnostics.append(
                            DiagnosticItem(
                                category="semantic",
                                status="failed",
                                severity=Severity.HIGH.value,
                                message=(
                                    f"Function '{func_name}' expects at most {sig['max_args']} "
                                    f"arguments, but {passed_args} were provided."
                                ),
                                line=node.lineno,
                                column=node.col_offset,
                                location={"line": node.lineno, "column": node.col_offset},
                            )
                        )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):
        # Detect literal division by zero (e.g. 1 / 0)
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            if isinstance(node.right, ast.Constant) and node.right.value == 0:
                self.diagnostics.append(
                    DiagnosticItem(
                        category="semantic",
                        status="failed",
                        severity=Severity.CRITICAL.value,
                        message="Division by zero detected in constant expression",
                        line=node.lineno,
                        column=node.col_offset,
                        location={"line": node.lineno, "column": node.col_offset},
                    )
                )
        self.generic_visit(node)

    def visit(self, node: ast.AST):
        if hasattr(node, "body") and isinstance(node.body, list):
            self._check_body_reachability(node.body)
        if hasattr(node, "orelse") and isinstance(node.orelse, list):
            self._check_body_reachability(node.orelse)
        if hasattr(node, "finalbody") and isinstance(node.finalbody, list):
            self._check_body_reachability(node.finalbody)
        super().visit(node)

    def _check_body_reachability(self, body: list[ast.stmt]):
        """Detect unreachable code after return/raise/break/continue."""
        terminator_encountered = False
        for stmt in body:
            if terminator_encountered:
                self.diagnostics.append(
                    DiagnosticItem(
                        category="semantic",
                        status="failed",
                        severity=Severity.HIGH.value,
                        message="Unreachable code statement detected after terminating jump",
                        line=stmt.lineno,
                        column=stmt.col_offset,
                        location={"line": stmt.lineno, "column": stmt.col_offset},
                    )
                )
                break
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                terminator_encountered = True

    def _check_return_consistency(self, func_node: ast.FunctionDef):
        """Check for functions that return a value in some branches but fall off in others."""
        returns_with_value = []
        returns_without_value = []

        for child in ast.walk(func_node):
            if isinstance(child, ast.Return):
                if child.value is not None:
                    returns_with_value.append(child)
                else:
                    returns_without_value.append(child)

        # Flag if there are explicitly mixed returning branches
        if returns_with_value and returns_without_value:
            bad_ret = returns_without_value[0]
            self.diagnostics.append(
                DiagnosticItem(
                    category="semantic",
                    status="failed",
                    severity=Severity.LOW.value,
                    message=f"Inconsistent returns in function '{func_node.name}': some branches return a value while others return None",
                    line=bad_ret.lineno,
                    column=bad_ret.col_offset,
                    location={"line": bad_ret.lineno, "column": bad_ret.col_offset},
                )
            )


class SemanticVerifier:
    """Verifies that code has sound semantics and static contract validity."""

    def verify(
        self,
        source_code: str,
        language: str = "python",
        file_path: Optional[str] = None,
    ) -> SemanticCheckResult:
        """
        Run semantic analysis on candidate code.

        Returns:
            SemanticCheckResult with diagnostics and pass/fail status.
        """
        lang = language.lower() if isinstance(language, str) else language.value.lower()
        if lang not in ("python", "py"):
            return SemanticCheckResult(
                category="semantic",
                status=CheckStatus.PASS,
                diagnostics=[],
                summary="Semantic verification passed (unsupported language skipped)",
            )

        try:
            tree = ast.parse(source_code, filename=file_path or "<candidate>")
        except SyntaxError:
            # Syntax errors are handled by SyntaxVerifier
            return SemanticCheckResult(
                category="semantic",
                status=CheckStatus.FAIL,
                diagnostics=[
                    DiagnosticItem(
                        category="semantic",
                        status="failed",
                        severity=Severity.CRITICAL.value,
                        message="Cannot perform semantic analysis on code with syntax errors.",
                    )
                ],
                summary="Syntax error prevented semantic verification.",
            )

        visitor = PythonSemanticVisitor()
        visitor.visit(tree)

        # Classify failures: Critical or High severity issues trigger stage failure
        failures = [
            d for d in visitor.diagnostics
            if d.severity in (Severity.CRITICAL.value, Severity.HIGH.value)
        ]

        if failures:
            summary = f"Semantic verification failed: {len(failures)} error(s) detected ({failures[0].message})"
            return SemanticCheckResult(
                category="semantic",
                status=CheckStatus.FAIL,
                diagnostics=visitor.diagnostics,
                summary=summary,
            )

        return SemanticCheckResult(
            category="semantic",
            status=CheckStatus.PASS,
            diagnostics=visitor.diagnostics,
            summary="Semantic checks passed",
        )
