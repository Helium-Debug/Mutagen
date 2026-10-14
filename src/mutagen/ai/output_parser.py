"""
AI response parser for MUTAGEN.

Extracts structured mutation candidates from raw AI responses,
with bounded recovery for malformed output.
"""

from __future__ import annotations

import json
import re
from typing import Any

from mutagen.core.identifiers import generate_mutation_id
from mutagen.core.security import compute_content_hash
from mutagen.exceptions import MutagenAIError
from mutagen.schemas import MutationCandidate, MutationResponse, MutationStrategy


# Maximum response size to prevent memory issues
MAX_RESPONSE_SIZE = 500_000  # 500KB


def parse_mutation_response(
    raw_response: str,
    model_id: str = "",
    usage: dict[str, Any] | None = None,
) -> MutationResponse:
    """
    Parse a raw AI response into a MutationResponse.

    Attempts bounded recovery for common formatting issues.

    Args:
        raw_response: Raw text from the AI provider.
        model_id: The model that generated the response.
        usage: Token usage information.

    Returns:
        Parsed MutationResponse with validated candidates.

    Raises:
        MutagenAIError: If the response cannot be parsed after recovery attempts.
    """
    if len(raw_response) > MAX_RESPONSE_SIZE:
        raise MutagenAIError(
            f"AI response exceeds maximum size: {len(raw_response)} > {MAX_RESPONSE_SIZE}"
        )

    # Try to extract JSON from the response
    data = _extract_json(raw_response)
    if data is None:
        raise MutagenAIError(
            "Could not parse AI response as JSON. "
            "The model did not return a valid structured response."
        )

    # Parse candidates
    candidates = []
    if isinstance(data, list):
        raw_candidates = data
    elif isinstance(data, dict):
        raw_candidates = data.get("candidates", [])
        if isinstance(raw_candidates, dict):
            if all(isinstance(v, (dict, str)) for v in raw_candidates.values()) and not any(k in raw_candidates for k in ("source_code", "code", "mutation_id")):
                raw_candidates = list(raw_candidates.values())
            else:
                raw_candidates = [raw_candidates]
        elif isinstance(raw_candidates, str):
            raw_candidates = [raw_candidates]
        elif not isinstance(raw_candidates, list) and ("source_code" in data or "code" in data or "mutation_id" in data):
            raw_candidates = [data]
    else:
        raw_candidates = []

    if not isinstance(raw_candidates, list):
        raise MutagenAIError("AI response 'candidates' field is not a list.")

    for i, raw_cand in enumerate(raw_candidates):
        try:
            candidate = _parse_single_candidate(raw_cand, i)
            candidates.append(candidate)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            # Skip malformed candidates but track the issue
            continue

    return MutationResponse(
        candidates=candidates,
        model_id=model_id,
        usage=usage or {},
        raw_response=raw_response[:1000],  # Truncate for storage
    )


def _extract_json(text: str) -> dict | None:
    """
    Extract JSON from text, handling markdown code fences.

    Tries multiple extraction strategies with bounded attempts.
    """
    # Strategy 1: Direct JSON parse
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from markdown code fence
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find first { to last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass

    # Strategy 4: Salvage completed candidates from truncated JSON
    first_brace = text.find("{")
    if first_brace != -1:
        text_from_brace = text[first_brace:]
        cand_idx = text_from_brace.find('"candidates"')
        if cand_idx != -1:
            last_pos = len(text_from_brace)
            while True:
                rbrace = text_from_brace.rfind("}", 0, last_pos)
                if rbrace == -1 or rbrace <= cand_idx:
                    break
                candidate_patch = text_from_brace[:rbrace + 1].strip().rstrip(",")
                for closing in ["]}", "\n]}\n", "}", "\n}\n"]:
                    try:
                        data = json.loads(candidate_patch + closing)
                        if isinstance(data, dict) and "candidates" in data and len(data["candidates"]) > 0:
                            return data
                    except json.JSONDecodeError:
                        pass
                last_pos = rbrace

    return None


def _clean_source_code(source: str) -> str:
    """Strip outer markdown code fences from source code if present."""
    s = source.strip()
    if s.startswith("```"):
        first_newline = s.find("\n")
        if first_newline != -1:
            s = s[first_newline + 1:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _parse_single_candidate(raw: Any, index: int) -> MutationCandidate:
    """Parse a single candidate from the AI response."""
    if isinstance(raw, str):
        raw_str = raw.strip()
        if raw_str.startswith("{") and raw_str.endswith("}"):
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, dict):
                    raw = parsed
            except Exception:
                pass
        if isinstance(raw, str):
            raw = {"source_code": raw_str, "strategy": "general"}
    elif not isinstance(raw, dict):
        raise ValueError(f"Candidate {index} is not an object or string")

    raw_source = raw.get("source_code") or raw.get("code") or ""
    source_code = _clean_source_code(str(raw_source))
    if not source_code:
        raise ValueError(f"Candidate {index} has no source code")

    # Parse strategy (supporting 'mutation_strategy' as alias)
    strategy_str = (
        raw.get("mutation_strategy")
        or raw.get("strategy")
        or "general"
    )
    strategy_str = str(strategy_str).lower().strip()
    try:
        strategy = MutationStrategy(strategy_str)
    except ValueError:
        strategy = MutationStrategy.GENERAL

    # Candidate ID
    candidate_id = raw.get("mutation_id") or raw.get("candidate_id")
    if not candidate_id or not isinstance(candidate_id, str):
        candidate_id = generate_mutation_id()

    content_hash = compute_content_hash(source_code)

    # Explanation and description
    description = str(raw.get("description", ""))[:2000]
    explanation = str(raw.get("explanation", ""))[:2000]
    if not explanation and description:
        explanation = description
    elif not description and explanation:
        description = explanation

    # Expected improvement / benefit
    expected_benefit = str(raw.get("expected_benefit", ""))[:1000]
    expected_improvement = str(raw.get("expected_improvement", ""))[:1000]
    if not expected_improvement and expected_benefit:
        expected_improvement = expected_benefit
    elif not expected_benefit and expected_improvement:
        expected_benefit = expected_improvement

    # Risks
    potential_risks = str(raw.get("potential_risks", ""))[:1000]
    risks_list = raw.get("risks", [])
    if isinstance(risks_list, list):
        parsed_risks = [str(r) for r in risks_list if str(r).strip()]
        if not potential_risks and parsed_risks:
            potential_risks = "; ".join(parsed_risks)[:1000]
    elif isinstance(risks_list, str) and risks_list.strip():
        parsed_risks = [risks_list.strip()]
        if not potential_risks:
            potential_risks = risks_list[:1000]
    else:
        parsed_risks = [potential_risks] if potential_risks else []

    # Required tests
    req_tests = raw.get("required_tests", [])
    if isinstance(req_tests, list):
        parsed_tests = [str(t) for t in req_tests if str(t).strip()]
    elif isinstance(req_tests, str) and req_tests.strip():
        parsed_tests = [req_tests.strip()]
    else:
        parsed_tests = []

    # Complexity analysis
    complexity = raw.get("complexity_analysis")
    if not isinstance(complexity, dict):
        complexity = None

    target_symbol = raw.get("target_symbol")
    if target_symbol is not None:
        target_symbol = str(target_symbol)[:200]

    return MutationCandidate(
        candidate_id=candidate_id,
        source_code=source_code,
        strategy=strategy,
        explanation=explanation,
        expected_improvement=expected_improvement,
        potential_risks=potential_risks,
        assumptions=str(raw.get("assumptions", ""))[:1000],
        content_hash=content_hash,
        target_symbol=target_symbol,
        description=description,
        expected_benefit=expected_benefit,
        complexity_analysis=complexity,
        risks=parsed_risks,
        required_tests=parsed_tests,
    )
