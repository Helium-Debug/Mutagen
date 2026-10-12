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
    raw_candidates = data.get("candidates", [])

    if not isinstance(raw_candidates, list):
        raise MutagenAIError("AI response 'candidates' field is not a list.")

    for i, raw_cand in enumerate(raw_candidates):
        try:
            candidate = _parse_single_candidate(raw_cand, i)
            candidates.append(candidate)
        except (ValueError, KeyError, TypeError) as e:
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


def _parse_single_candidate(raw: dict, index: int) -> MutationCandidate:
    """Parse a single candidate from the AI response."""
    source_code = raw.get("source_code", "").strip()
    if not source_code:
        raise ValueError(f"Candidate {index} has no source code")

    # Parse strategy
    strategy_str = raw.get("strategy", "general").lower().strip()
    try:
        strategy = MutationStrategy(strategy_str)
    except ValueError:
        strategy = MutationStrategy.GENERAL

    candidate_id = generate_mutation_id()
    content_hash = compute_content_hash(source_code)

    return MutationCandidate(
        candidate_id=candidate_id,
        source_code=source_code,
        strategy=strategy,
        explanation=str(raw.get("explanation", ""))[:2000],
        expected_improvement=str(raw.get("expected_improvement", ""))[:1000],
        potential_risks=str(raw.get("potential_risks", ""))[:1000],
        assumptions=str(raw.get("assumptions", ""))[:1000],
        content_hash=content_hash,
    )
