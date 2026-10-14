"""
Automated Code Repair Subsystem for MUTAGEN.

When tests or verification checks fail, this service diagnoses the failure
and uses the locally available Gemma 2 model (e.g. gemma2:2b) via Ollama
to repair the code and update the file so that it is correct.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Optional

import requests

from mutagen.config import get_settings
from mutagen.core.logging import get_logger
from mutagen.verification.syntax import SyntaxVerifier

logger = get_logger("ai.repair")


class CodeRepairResult:
    """Outcome of an automated code repair attempt."""

    def __init__(
        self,
        success: bool,
        original_code: str,
        repaired_code: Optional[str] = None,
        file_path: Optional[str] = None,
        model_used: str = "gemma2:2b",
        error_message: Optional[str] = None,
        changes_made: bool = False,
    ):
        self.success = success
        self.original_code = original_code
        self.repaired_code = repaired_code or original_code
        self.file_path = file_path
        self.model_used = model_used
        self.error_message = error_message
        self.changes_made = changes_made

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "model_used": self.model_used,
            "file_path": self.file_path,
            "changes_made": self.changes_made,
            "error_message": self.error_message,
        }


class CodeRepairService:
    """
    Automated code repair powered by the locally available Gemma 2 model.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_id: Optional[str] = None,
        timeout: int = 90,
    ):
        settings = get_settings()
        self.base_url = (base_url or getattr(settings, "gemma_base_url", "http://localhost:11434")).rstrip("/")
        self.model_id = model_id or self._detect_local_gemma2_model()
        self.timeout = timeout
        self.syntax_verifier = SyntaxVerifier()

    def _detect_local_gemma2_model(self) -> str:
        """Find the local Gemma 2 model installed in Ollama."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                # Prioritize gemma2 models
                for m in models:
                    if "gemma2" in m.lower():
                        logger.info(f"Detected local Gemma 2 model: {m}")
                        return m
                for m in models:
                    if "gemma" in m.lower():
                        return m
        except Exception as e:
            logger.debug(f"Could not query Ollama tags: {e}")

        # Default fallback
        return "gemma2:2b"

    def repair_code(
        self,
        code: str,
        failures: list[str] | str,
        language: str = "python",
    ) -> CodeRepairResult:
        """
        Repair source code using local Gemma 2 model.
        """
        if isinstance(failures, list):
            failure_str = "\n".join(f"- {f}" for f in failures if f)
        else:
            failure_str = str(failures)

        prompt = f"""You are the automated code repair engine for MUTAGEN.
The following source code failed verification or testing:

```{language}
{code}
```

FAILURES DETECTED:
{failure_str}

TASK:
1. Identify the bug or logical error causing the failure.
2. Correct the code so that all tests pass and logic is completely sound.
3. Preserve existing function signatures, docstrings, classes, and structure.
4. Output ONLY the complete, corrected source code in a ```{language} ... ``` markdown block. Do not provide chatty explanations.
"""

        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model_id,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_ctx": 8192,
                    },
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_response = data.get("response", "")

            # Track token usage in centralized repository
            try:
                from mutagen.ai.reduction import TokenReductionEngine
                in_tok = data.get("prompt_eval_count")
                out_tok = data.get("eval_count")
                tot_tok = (in_tok + out_tok) if (in_tok is not None and out_tok is not None) else None
                engine = TokenReductionEngine()
                engine.record_usage(
                    provider="gemma",
                    model=self.model_id,
                    operation="code_repair",
                    usage_data={
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "total_tokens": tot_tok,
                    },
                    estimated_prompt=prompt,
                    estimated_completion=raw_response,
                )
            except Exception as ex:
                logger.debug(f"Could not record code repair token usage: {ex}")
        except Exception as e:
            logger.error(f"Gemma 2 repair call failed: {e}")
            return CodeRepairResult(
                success=False,
                original_code=code,
                model_used=self.model_id,
                error_message=f"Local Gemma 2 model call failed: {e}",
            )

        extracted = self._extract_code(raw_response, language)
        if not extracted or extracted.strip() == "":
            return CodeRepairResult(
                success=False,
                original_code=code,
                model_used=self.model_id,
                error_message="Failed to extract corrected code from model output",
            )

        # Validate syntax of repaired code
        syn_result = self.syntax_verifier.verify(extracted, language=language)
        if not syn_result.passed:
            return CodeRepairResult(
                success=False,
                original_code=code,
                repaired_code=extracted,
                model_used=self.model_id,
                error_message=f"Repaired code has syntax error: {syn_result.message}",
            )

        changes_made = (extracted.strip() != code.strip())
        return CodeRepairResult(
            success=True,
            original_code=code,
            repaired_code=extracted,
            model_used=self.model_id,
            changes_made=changes_made,
        )

    def repair_file(
        self,
        file_path: str | Path,
        failures: list[str] | str,
        language: str = "python",
    ) -> CodeRepairResult:
        """
        Read file, repair code using local Gemma 2, and write the corrected code back to the file.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            return CodeRepairResult(
                success=False,
                original_code="",
                file_path=str(path),
                model_used=self.model_id,
                error_message=f"File not found: {path}",
            )

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return CodeRepairResult(
                success=False,
                original_code="",
                file_path=str(path),
                model_used=self.model_id,
                error_message=f"Could not read file {path}: {e}",
            )

        result = self.repair_code(code=content, failures=failures, language=language)
        result.file_path = str(path)

        if result.success and result.changes_made and result.repaired_code:
            try:
                path.write_text(result.repaired_code, encoding="utf-8")
                logger.info(f"Updated file {path} with corrected code from {self.model_id}")
            except Exception as e:
                result.success = False
                result.error_message = f"Failed to write repaired code to {path}: {e}"

        return result

    def _extract_code(self, text: str, language: str) -> str:
        """Extract clean code from markdown code fences or raw text."""
        # Check for ```python ... ``` or ``` ... ```
        pattern = rf"```(?:{language})?\s*\n(.*?)```"
        matches = re.findall(pattern, text, flags=re.DOTALL | re.IGNORECASE)
        if matches:
            # Pick longest match
            return max(matches, key=len).strip()

        # If no markdown fences, check if text itself parses as valid python
        text_clean = text.strip()
        try:
            ast.parse(text_clean)
            return text_clean
        except SyntaxError:
            pass

        # Try to strip leading/trailing conversational text
        lines = text_clean.splitlines()
        code_lines = []
        for line in lines:
            if line.strip().startswith("```"):
                continue
            code_lines.append(line)
        return "\n".join(code_lines).strip()
