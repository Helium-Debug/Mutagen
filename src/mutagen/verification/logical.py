"""
Logical Verification Stage for MUTAGEN.

Integrates Gemma 4 as a reasoning-based semantic and logical correctness verifier.
Analyzes original code, candidate, diff, tests, and execution results to detect
subtle behavioral flaws, edge cases, and unintended side-effects.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from mutagen.ai.base import AIProviderBase
from mutagen.ai.output_parser import _extract_json
from mutagen.core.logging import get_logger
from mutagen.verification.schemas import (
    CheckStatus, LogicalAnalysisResult, VerificationVerdict,
)

logger = get_logger("verification.logical")


def build_logical_verification_prompt(
    original_code: str,
    candidate_code: str,
    diff: str = "",
    tests: str = "No dedicated tests provided",
    test_results: str = "Execution succeeded",
    static_analysis: str = "Syntax valid",
    runtime_results: str = "Exit code 0",
    complexity_results: str = "Complexity preserved",
) -> str:
    """Build the exact Gemma 4 verification prompt as per Section 6 specifications."""
    return f"""You are the correctness verifier for MUTAGEN.

Your task is NOT to optimize the code.

Your task is to determine whether the evolved candidate preserves
the intended behavior of the original program.

ORIGINAL CODE:
{original_code.strip()}

EVOLVED CODE:
{candidate_code.strip()}

MUTATION DIFF:
{diff.strip() if diff else "None"}

AVAILABLE TESTS:
{tests.strip() if tests else "None"}

TEST RESULTS:
{test_results.strip() if test_results else "None"}

STATIC ANALYSIS:
{static_analysis.strip() if static_analysis else "None"}

RUNTIME RESULTS:
{runtime_results.strip() if runtime_results else "None"}

COMPLEXITY RESULTS:
{complexity_results.strip() if complexity_results else "None"}

Analyze the candidate for:

1. Logical correctness
2. Behavioral equivalence
3. Edge cases
4. Boundary conditions
5. Error handling
6. State changes
7. Return values
8. Algorithmic correctness
9. Possible regressions
10. Incorrect assumptions introduced by the mutation

Do not assume that passing tests means the candidate is correct.

Look for cases that the existing tests may not cover.

Return ONLY valid JSON.

Required schema:
{{
  "verdict": "PASS | FAIL | UNCERTAIN",
  "confidence": 0.0,
  "logical_correctness": {{
    "status": "PASS | FAIL | UNCERTAIN",
    "reason": ""
  }},
  "behavior_preservation": {{
    "status": "PASS | FAIL | UNCERTAIN",
    "reason": ""
  }},
  "edge_cases": [
    {{
      "case": "",
      "risk": "LOW | MEDIUM | HIGH",
      "reason": ""
    }}
  ],
  "detected_errors": [
    {{
      "type": "LOGICAL | SEMANTIC | RUNTIME | REGRESSION",
      "severity": "LOW | MEDIUM | HIGH | CRITICAL",
      "location": "",
      "description": ""
    }}
  ],
  "suggested_tests": [],
  "recommendation": "ACCEPT | REJECT | REVIEW"
}}
"""


class LogicalVerifier:
    """Invokes Gemma 4 for deep reasoning-based logical correctness verification."""

    def __init__(self, ai_provider: Optional[AIProviderBase] = None):
        self.ai = ai_provider

    def verify(
        self,
        original_code: str,
        candidate_code: str,
        diff: str = "",
        tests: str = "",
        test_results: str = "",
        static_analysis: str = "",
        runtime_results: str = "",
        complexity_results: str = "",
    ) -> LogicalAnalysisResult:
        """
        Run logical verification against the AI reasoning model.

        If the AI provider is unavailable or fails, returns an UNAVAILABLE / REVIEW status
        rather than fabricating any result.
        """
        if self.ai is None:
            return LogicalAnalysisResult(
                verdict=CheckStatus.UNAVAILABLE,
                confidence=0.0,
                logical_correctness={
                    "status": "UNAVAILABLE",
                    "reason": "AI provider not configured",
                },
                behavior_preservation={
                    "status": "UNAVAILABLE",
                    "reason": "AI provider not configured",
                },
                recommendation=VerificationVerdict.REVIEW,
            )

        prompt = build_logical_verification_prompt(
            original_code=original_code,
            candidate_code=candidate_code,
            diff=diff,
            tests=tests,
            test_results=test_results,
            static_analysis=static_analysis,
            runtime_results=runtime_results,
            complexity_results=complexity_results,
        )

        system_instruction = (
            "You are MUTAGEN's correctness verifier. Determine whether the evolved "
            "candidate strictly preserves the intended behavior. Respond ONLY with valid JSON."
        )

        try:
            # Check if provider has verify_candidate method
            if hasattr(self.ai, "verify_candidate"):
                raw_response = self.ai.verify_candidate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                )
            elif hasattr(self.ai, "_call_with_retry"):
                raw_response, _ = self.ai._call_with_retry(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    operation="logical_verification",
                    require_json=True,
                )
            else:
                # Fallback generic call
                raw_response = self.ai.explain_change(
                    original=original_code,
                    candidate=candidate_code,
                    language="python",
                )
        except Exception as e:
            logger.warning(f"Logical verification failed during model call: {e}")
            return LogicalAnalysisResult(
                verdict=CheckStatus.UNAVAILABLE,
                confidence=0.0,
                logical_correctness={
                    "status": "UNAVAILABLE",
                    "reason": f"AI verification server unavailable: {e}",
                },
                behavior_preservation={
                    "status": "UNAVAILABLE",
                    "reason": "Inference failure",
                },
                recommendation=VerificationVerdict.REVIEW,
            )

        # Parse JSON
        parsed = _extract_json(raw_response) if isinstance(raw_response, str) else raw_response
        if not isinstance(parsed, dict):
            logger.warning("Logical verifier received unparseable response from AI model")
            return LogicalAnalysisResult(
                verdict=CheckStatus.UNCERTAIN,
                confidence=0.5,
                logical_correctness={
                    "status": "UNCERTAIN",
                    "reason": "Model returned unstructured response",
                },
                behavior_preservation={
                    "status": "UNCERTAIN",
                    "reason": "Could not parse JSON",
                },
                recommendation=VerificationVerdict.REVIEW,
                raw_model_response=str(raw_response)[:1000],
            )

        # Extract structured fields
        verdict_str = str(parsed.get("verdict", "UNCERTAIN")).upper()
        verdict = (
            CheckStatus.PASS if verdict_str == "PASS"
            else CheckStatus.FAIL if verdict_str == "FAIL"
            else CheckStatus.UNCERTAIN
        )

        try:
            confidence = float(parsed.get("confidence", 0.8))
        except (ValueError, TypeError):
            confidence = 0.5

        rec_str = str(parsed.get("recommendation", "REVIEW")).upper()
        recommendation = (
            VerificationVerdict.ACCEPT if rec_str == "ACCEPT"
            else VerificationVerdict.REJECT if rec_str == "REJECT"
            else VerificationVerdict.REVIEW
        )

        # Normalize suggested_tests
        raw_suggested = parsed.get("suggested_tests", [])
        suggested_tests: list[Any] = []
        if isinstance(raw_suggested, list):
            for t in raw_suggested:
                if isinstance(t, dict):
                    desc = t.get("description") or t.get("case") or t.get("test") or str(t)
                    inp = t.get("input")
                    if inp is not None:
                        suggested_tests.append(f"Input {inp}: {desc}")
                    else:
                        suggested_tests.append(str(desc))
                else:
                    suggested_tests.append(str(t))
        elif isinstance(raw_suggested, (str, dict)):
            suggested_tests.append(str(raw_suggested))

        # Normalize edge_cases & detected_errors
        raw_edges = parsed.get("edge_cases", [])
        edge_cases = raw_edges if isinstance(raw_edges, list) else []

        raw_errors = parsed.get("detected_errors", [])
        detected_errors = raw_errors if isinstance(raw_errors, list) else []

        # Normalize logical_correctness & behavior_preservation
        log_corr = parsed.get("logical_correctness", {"status": verdict_str, "reason": ""})
        if not isinstance(log_corr, dict):
            log_corr = {"status": verdict_str, "reason": str(log_corr)}

        beh_pres = parsed.get("behavior_preservation", {"status": verdict_str, "reason": ""})
        if not isinstance(beh_pres, dict):
            beh_pres = {"status": verdict_str, "reason": str(beh_pres)}

        return LogicalAnalysisResult(
            verdict=verdict,
            confidence=max(0.0, min(1.0, confidence)),
            logical_correctness=log_corr,
            behavior_preservation=beh_pres,
            edge_cases=edge_cases,
            detected_errors=detected_errors,
            suggested_tests=suggested_tests,
            recommendation=recommendation,
            raw_model_response=str(raw_response)[:2000],
        )
