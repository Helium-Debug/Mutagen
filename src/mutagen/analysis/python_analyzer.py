"""
Python-specific code analysis using the AST module.

Performs syntax validation, structure analysis, interface extraction,
and complexity metrics without executing the target code.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Optional

from mutagen.core.security import compute_content_hash
from mutagen.schemas import (
    CodeAnalysis, ClassInfo, FunctionInfo, ImportInfo, ProgrammingLanguage,
)


class PythonAnalyzer:
    """
    Analyzes Python source code using AST parsing.

    Does NOT execute the target code. All analysis is static.
    """

    def analyze(self, source: str, file_path: str = "<input>") -> CodeAnalysis:
        """
        Perform comprehensive Python source analysis.

        Args:
            source: Python source code text.
            file_path: Path for error reporting.

        Returns:
            A CodeAnalysis result with all findings.
        """
        analysis = CodeAnalysis(
            language=ProgrammingLanguage.PYTHON,
            file_path=file_path,
            source_hash=compute_content_hash(source),
        )

        # Line counts
        lines = source.splitlines()
        analysis.lines_total = len(lines)
        analysis.lines_blank = sum(1 for line in lines if not line.strip())
        analysis.lines_comment = sum(
            1 for line in lines if line.strip().startswith("#")
        )
        analysis.lines_code = (
            analysis.lines_total - analysis.lines_blank - analysis.lines_comment
        )

        # Syntax validation
        try:
            tree = ast.parse(source, filename=file_path)
            analysis.syntax_valid = True
        except SyntaxError as e:
            analysis.syntax_valid = False
            analysis.syntax_errors.append(
                f"Line {e.lineno}: {e.msg}" if e.lineno else str(e.msg)
            )
            return analysis

        # Walk the AST to extract information
        analysis.functions = self._extract_functions(tree)
        analysis.classes = self._extract_classes(tree)
        analysis.imports = self._extract_imports(tree)
        analysis.public_interface = self._extract_public_interface(tree)
        analysis.complexity_score = self._calculate_complexity(tree)

        # Algorithmic Complexity Estimation
        max_loop_depth = self._max_loop_depth(tree)
        has_recursion = self._detect_recursion(tree)
        analysis.max_loop_depth = max_loop_depth
        analysis.estimated_time_complexity = self._estimate_time_complexity(max_loop_depth, has_recursion)
        analysis.estimated_space_complexity = self._estimate_space_complexity(tree, max_loop_depth)

        # Real-time runtime and memory profiling
        runtime_profile = self._profile_runtime(source, file_path)
        if runtime_profile:
            analysis.runtime_seconds = runtime_profile.get("runtime_seconds")
            analysis.cpu_time_seconds = runtime_profile.get("cpu_time_seconds")
            analysis.memory_peak_mb = runtime_profile.get("memory_peak_mb")

        # Warnings
        analysis.warnings = self._generate_warnings(tree, source)

        return analysis

    def validate_syntax(self, source: str) -> tuple[bool, list[str]]:
        """
        Check if the Python source is syntactically valid.

        Returns:
            Tuple of (is_valid, list_of_errors).
        """
        try:
            ast.parse(source)
            return True, []
        except SyntaxError as e:
            error_msg = f"Line {e.lineno}: {e.msg}" if e.lineno else str(e.msg)
            return False, [error_msg]

    def extract_public_interface(self, source: str) -> list[str]:
        """Extract public function and class names from source code."""
        try:
            tree = ast.parse(source)
            return self._extract_public_interface(tree)
        except SyntaxError:
            return []

    def _extract_functions(self, tree: ast.Module) -> list[FunctionInfo]:
        """Extract top-level and nested function information."""
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_info = FunctionInfo(
                    name=node.name,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", None),
                    args=[arg.arg for arg in node.args.args],
                    decorators=[self._get_decorator_name(d) for d in node.decorator_list],
                    docstring=ast.get_docstring(node),
                    is_async=isinstance(node, ast.AsyncFunctionDef),
                    complexity=self._function_complexity(node),
                )
                functions.append(func_info)
        return functions

    def _extract_classes(self, tree: ast.Module) -> list[ClassInfo]:
        """Extract class information."""
        classes = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = []
                for item in ast.walk(node):
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(FunctionInfo(
                            name=item.name,
                            lineno=item.lineno,
                            end_lineno=getattr(item, "end_lineno", None),
                            args=[arg.arg for arg in item.args.args],
                            decorators=[self._get_decorator_name(d) for d in item.decorator_list],
                            docstring=ast.get_docstring(item),
                            is_async=isinstance(item, ast.AsyncFunctionDef),
                            complexity=self._function_complexity(item),
                        ))

                class_info = ClassInfo(
                    name=node.name,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", None),
                    bases=[self._get_name(base) for base in node.bases],
                    methods=methods,
                    decorators=[self._get_decorator_name(d) for d in node.decorator_list],
                    docstring=ast.get_docstring(node),
                )
                classes.append(class_info)
        return classes

    def _extract_imports(self, tree: ast.Module) -> list[ImportInfo]:
        """Extract import statements."""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ImportInfo(
                        module=alias.name,
                        names=[alias.asname or alias.name],
                        is_from_import=False,
                        lineno=node.lineno,
                    ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [alias.name for alias in node.names]
                imports.append(ImportInfo(
                    module=module,
                    names=names,
                    is_from_import=True,
                    lineno=node.lineno,
                ))
        return imports

    def _extract_public_interface(self, tree: ast.Module) -> list[str]:
        """
        Extract public interface: names of public functions, classes, and variables.

        Public names are those that don't start with an underscore.
        """
        public = []

        # Check for __all__
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    public.append(elt.value)
                            return public

        # Fallback: all top-level non-underscore names
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    public.append(node.name)
            elif isinstance(node, ast.ClassDef):
                if not node.name.startswith("_"):
                    public.append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and not target.id.startswith("_"):
                        public.append(target.id)

        return public

    def _calculate_complexity(self, tree: ast.Module) -> float:
        """
        Calculate a simplified cyclomatic complexity for the module.

        Each decision point (if, elif, for, while, try, with, boolean op)
        adds 1 to the complexity. Base complexity is 1.
        """
        complexity = 1
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try,
                                 ast.With, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
        return float(complexity)

    def _function_complexity(self, node: ast.AST) -> int:
        """Calculate complexity of a single function."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try,
                                  ast.With, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity

    def _get_decorator_name(self, node: ast.expr) -> str:
        """Extract decorator name as string."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_decorator_name(node.func)
        return "<unknown>"

    def _get_name(self, node: ast.expr) -> str:
        """Extract a name from various AST node types."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Constant):
            return str(node.value)
        return "<unknown>"

    def _generate_warnings(self, tree: ast.Module, source: str) -> list[str]:
        """Generate analysis warnings."""
        warnings = []

        # Check for overly long functions
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = getattr(node, "end_lineno", None)
                if end_line and (end_line - node.lineno) > 50:
                    warnings.append(
                        f"Function '{node.name}' is {end_line - node.lineno} lines long "
                        f"(consider refactoring)"
                    )

        # Check for deeply nested code
        max_depth = self._max_nesting_depth(tree)
        if max_depth > 5:
            warnings.append(f"Maximum nesting depth is {max_depth} (consider simplifying)")

        # Check for too many arguments
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n_args = len(node.args.args)
                if n_args > 7:
                    warnings.append(
                        f"Function '{node.name}' has {n_args} parameters (consider grouping)"
                    )

        return warnings

    def _max_nesting_depth(self, tree: ast.Module, depth: int = 0) -> int:
        """Calculate maximum nesting depth."""
        max_depth = depth
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                child_depth = self._max_nesting_depth(node, depth + 1)  # type: ignore
                max_depth = max(max_depth, child_depth)
        return max_depth

    def _max_loop_depth(self, node: ast.AST, current: int = 0) -> int:
        """Calculate the maximum loop nesting depth (for, while)."""
        max_depth = current
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.For, ast.While)):
                child_depth = self._max_loop_depth(child, current + 1)
                max_depth = max(max_depth, child_depth)
            else:
                child_depth = self._max_loop_depth(child, current)
                max_depth = max(max_depth, child_depth)
        return max_depth

    def _detect_recursion(self, tree: ast.Module) -> bool:
        """Detect whether any function contains recursive calls to itself."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_name = node.name
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name) and child.func.id == fn_name:
                            return True
        return False

    def _estimate_time_complexity(self, max_loop_depth: int, has_recursion: bool) -> str:
        """Estimate Big-O time complexity."""
        if has_recursion:
            if max_loop_depth >= 1:
                return "O(2ⁿ) [Exponential / Branching Recursion]"
            return "O(2ⁿ) or O(n) [Recursive Calls]"
        if max_loop_depth == 0:
            return "O(1) [Constant]"
        elif max_loop_depth == 1:
            return "O(n) [Linear]"
        elif max_loop_depth == 2:
            return "O(n²) [Quadratic - 2 Nested Loops]"
        elif max_loop_depth == 3:
            return "O(n³) [Cubic - 3 Nested Loops]"
        else:
            return f"O(n^{max_loop_depth}) [Polynomial - {max_loop_depth} Nested Loops]"

    def _estimate_space_complexity(self, tree: ast.Module, max_loop_depth: int) -> str:
        """Estimate Big-O space complexity."""
        has_dynamic_collections = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
                has_dynamic_collections = True
                break
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"list", "dict", "set"}:
                    has_dynamic_collections = True
                    break
        if has_dynamic_collections or max_loop_depth > 0:
            return "O(n) [Linear Auxiliary Memory]"
        return "O(1) [Constant In-Place Memory]"

    def _profile_runtime(self, source: str, file_path: str, timeout: float = 3.0) -> Optional[dict]:
        """Safely profile runtime wall time, CPU time, and peak memory in an isolated subprocess."""
        import subprocess
        import sys
        import tempfile
        import json

        runner_code = (
            "import sys, time, tracemalloc, json\n"
            "tracemalloc.start()\n"
            "c0 = time.process_time()\n"
            "t0 = time.perf_counter()\n"
            "try:\n"
            "    exec(compile(open(sys.argv[1], 'r', encoding='utf-8').read(), sys.argv[1], 'exec'), {'__name__': '__main__'})\n"
            "    t1 = time.perf_counter()\n"
            "    c1 = time.process_time()\n"
            "    _, peak = tracemalloc.get_traced_memory()\n"
            "    tracemalloc.stop()\n"
            "    print(json.dumps({'runtime_seconds': t1 - t0, 'cpu_time_seconds': c1 - c0, 'memory_peak_mb': peak / (1024 * 1024)}))\n"
            "except Exception:\n"
            "    tracemalloc.stop()\n"
            "    sys.exit(1)\n"
        )

        temp_target = None
        try:
            p = Path(file_path)
            if p.exists() and p.is_file():
                target_path = str(p.resolve())
            else:
                with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
                    tf.write(source)
                    temp_target = tf.name
                target_path = temp_target

            proc = subprocess.run(
                [sys.executable, "-c", runner_code, target_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if proc.returncode == 0:
                for line in proc.stdout.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        return json.loads(line)
        except Exception:
            pass
        finally:
            if temp_target and Path(temp_target).exists():
                try:
                    Path(temp_target).unlink()
                except Exception:
                    pass
        return None
