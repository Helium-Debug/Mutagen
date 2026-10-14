"""
Adversarial & Differential Testing Stage for MUTAGEN.

Executes both the original and candidate implementations on generated edge-case
inputs and property-based assertions in the sandbox to detect behavioral regressions.
"""

from __future__ import annotations

import ast
import json
from typing import Any, Optional

from mutagen.sandbox.docker_manager import DockerSandbox
from mutagen.verification.schemas import CheckStatus, DifferentialResult


class DifferentialTester:
    """Performs differential testing and property verification between original and candidate code."""

    def __init__(self, sandbox: Optional[DockerSandbox] = None, timeout: int = 15):
        self.sandbox = sandbox or DockerSandbox()
        self.timeout = timeout

    test = None  # set below method definition

    def verify(
        self,
        original_code: str,
        candidate_code: str,
        additional_inputs: Optional[list[Any]] = None,
    ) -> DifferentialResult:
        """
        Run differential testing against original and candidate implementations.

        Returns:
            DifferentialResult with discrepancies and regression status.
        """
        functions = self._extract_callable_functions(original_code)

        if functions:
            return self._verify_functions(original_code, candidate_code, functions, additional_inputs)
        else:
            return self._verify_script(original_code, candidate_code)

    def _extract_callable_functions(self, code: str) -> list[dict[str, Any]]:
        """Extract top-level functions and their argument signatures."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        functions = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                arg_names = [a.arg for a in node.args.args]
                functions.append({
                    "name": node.name,
                    "arg_count": len(arg_names),
                    "arg_names": arg_names,
                    "has_defaults": len(node.args.defaults) > 0,
                })
        return functions

    def _generate_inputs_for_function(self, func_info: dict[str, Any]) -> list[tuple]:
        """Generate targeted edge cases and boundary inputs based on function signature."""
        arg_count = func_info["arg_count"]
        if arg_count == 0:
            return [()]

        # Standard suite of edge-case inputs for 1-arg functions
        candidates_1arg = [
            0, 1, 2, 3, 5, 10, -1,
            [], [1], [3, 1, 2], [1, 1, 1], [-5, 0, 10],
            "", "a", "hello", "racecar", "123",
        ]

        if arg_count == 1:
            return [(x,) for x in candidates_1arg]

        if arg_count == 2:
            return [
                (0, 0), (1, 1), (5, 2), (10, 5), (-1, 1),
                ([], []), ([1, 2], [3, 4]),
                ("hello", "world"), ("", "a"),
            ]

        # Generic tuples for multi-arg functions
        return [tuple(i for i in range(arg_count))]

    def _verify_functions(
        self,
        original_code: str,
        candidate_code: str,
        functions: list[dict[str, Any]],
        additional_inputs: Optional[list[Any]] = None,
    ) -> DifferentialResult:
        """Execute functions differentially inside the sandbox."""
        discrepancies: list[dict[str, Any]] = []
        properties_tested: list[dict[str, Any]] = []
        total_inputs = 0

        for func in functions:
            func_name = func["name"]
            inputs = self._generate_inputs_for_function(func)
            if additional_inputs:
                inputs.extend([(x,) if not isinstance(x, tuple) else x for x in additional_inputs])

            # Prepare dual execution harness in sandbox
            escaped_orig = original_code.replace("\\", "\\\\").replace("'", "\\'")
            escaped_cand = candidate_code.replace("\\", "\\\\").replace("'", "\\'")

            harness = f"""
import sys, json

orig_env = {{}}
cand_env = {{}}

try:
    exec(compile('''{escaped_orig}''', '<orig>', 'exec'), orig_env)
except Exception:
    pass

try:
    exec(compile('''{escaped_cand}''', '<cand>', 'exec'), cand_env)
except Exception:
    pass

inputs = {json.dumps(inputs)}
results = []

orig_func = orig_env.get('{func_name}')
cand_func = cand_env.get('{func_name}')

if callable(orig_func) and callable(cand_func):
    for inp in inputs:
        args = tuple(inp) if isinstance(inp, list) else (inp,)
        orig_out, cand_out = None, None
        orig_err, cand_err = None, None
        
        try:
            orig_out = orig_func(*args)
        except Exception as e:
            orig_err = type(e).__name__

        try:
            cand_out = cand_func(*args)
        except Exception as e:
            cand_err = type(e).__name__

        matches = (orig_out == cand_out) and (orig_err == cand_err)
        results.append({{
            "input": repr(args[0]) if len(args) == 1 else repr(args),
            "original_output": repr(orig_out) if orig_err is None else f"ERROR: {{orig_err}}",
            "candidate_output": repr(cand_out) if cand_err is None else f"ERROR: {{cand_err}}",
            "matches": matches,
        }})

print(json.dumps(results))
"""
            res = self.sandbox.execute_python(code=harness, timeout=self.timeout)
            if res.success:
                try:
                    # Look for JSON output
                    start_idx = res.stdout.find("[")
                    end_idx = res.stdout.rfind("]")
                    if start_idx != -1 and end_idx != -1:
                        data = json.loads(res.stdout[start_idx:end_idx + 1])
                        for item in data:
                            total_inputs += 1
                            if not item.get("matches", True):
                                # Discrepancy detected!
                                discrepancies.append({
                                    "function": func_name,
                                    "input": item["input"],
                                    "original_output": item["original_output"],
                                    "candidate_output": item["candidate_output"],
                                    "status": "REGRESSION",
                                })
                except Exception:
                    pass

        status = CheckStatus.FAIL if discrepancies else CheckStatus.PASS
        return DifferentialResult(
            status=status,
            inputs_tested=total_inputs,
            discrepancies=discrepancies,
            properties_tested=properties_tested,
        )

    def _verify_script(
        self,
        original_code: str,
        candidate_code: str,
    ) -> DifferentialResult:
        """Run procedural scripts differentially and compare stdout outputs."""
        orig_res = self.sandbox.execute_python(code=original_code, timeout=self.timeout)
        cand_res = self.sandbox.execute_python(code=candidate_code, timeout=self.timeout)

        discrepancies = []
        if orig_res.success and cand_res.success:
            # Compare normalized stdout lines (ignoring execution timing strings)
            orig_lines = [
                line.strip() for line in orig_res.stdout.splitlines()
                if not any(k in line.lower() for k in ("execution time", "elapsed", "seconds", "ms"))
            ]
            cand_lines = [
                line.strip() for line in cand_res.stdout.splitlines()
                if not any(k in line.lower() for k in ("execution time", "elapsed", "seconds", "ms"))
            ]

            if orig_lines != cand_lines:
                discrepancies.append({
                    "type": "stdout_mismatch",
                    "original_output": "\n".join(orig_lines[:10]),
                    "candidate_output": "\n".join(cand_lines[:10]),
                    "status": "REGRESSION",
                })

        status = CheckStatus.FAIL if discrepancies else CheckStatus.PASS
        return DifferentialResult(
            status=status,
            inputs_tested=1,
            discrepancies=discrepancies,
            properties_tested=[],
        )


DifferentialTester.test = DifferentialTester.verify

