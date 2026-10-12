"""
Prompt construction utilities for MUTAGEN AI providers.

Constructs detailed, structured prompts for mutation generation,
explanation, and summarization.
"""

from __future__ import annotations

import json
from typing import Optional

from mutagen.schemas import (
    CodeAnalysis, MemoryContext, OptimizationObjective,
)


def build_mutation_prompt(
    source_code: str,
    language: str,
    analysis: CodeAnalysis,
    objective: OptimizationObjective,
    memory_context: Optional[MemoryContext] = None,
    previous_failures: Optional[list[str]] = None,
    candidate_count: int = 4,
) -> str:
    """Build the prompt for generating code mutation candidates."""
    objective_guidance = {
        OptimizationObjective.SPEED: (
            "Primary objective: SPEED. Focus on reducing algorithmic time complexity (e.g. O(2^n) -> O(n)), "
            "eliminating redundant computations, memoization/caching, optimizing loops, and vectorization."
        ),
        OptimizationObjective.MEMORY: (
            "Primary objective: MEMORY. Focus on minimizing memory allocation, replacing large lists with "
            "generators or iterators, streaming data, in-place modifications, and compact data structures."
        ),
        OptimizationObjective.BALANCED: (
            "Primary objective: BALANCED. Improve execution speed and memory efficiency while preserving "
            "code readability, maintainability, and clean software design."
        ),
    }

    guidance = objective_guidance.get(
        objective, objective_guidance[OptimizationObjective.BALANCED]
    )

    prompt_parts = [
        f"You are the mutation engine of MUTAGEN, an experimental code evolution system.",
        f"Your task is to propose {candidate_count} distinct, optimized candidate implementations of the target code.",
        "",
        "=== OPTIMIZATION GOAL ===",
        guidance,
        "",
        "=== STRICT CONSTRAINTS ===",
        "1. PRESERVE PUBLIC INTERFACE: All existing function signatures, class interfaces, and expected return types MUST remain compatible.",
        "2. COMPLETE CODE: Return the entire, runnable code for each candidate (no placeholders, no `...`, no ellipses).",
        "3. SYNTACTICALLY VALID: Ensure the code parses and executes without syntax or runtime errors.",
        f"4. TARGET LANGUAGE: {language.upper()}",
    ]

    # Include analysis context
    prompt_parts.extend([
        "",
        "=== CODE ANALYSIS CONTEXT ===",
        f"- Lines of code: {analysis.lines_code}",
        f"- Cyclomatic complexity: {analysis.complexity_score:.1f}",
        f"- Public interface functions: {', '.join(analysis.public_interface) if analysis.public_interface else 'All module functions'}",
    ])

    # Include memory context if present
    if memory_context and memory_context.total_records > 0:
        prompt_parts.extend(["", "=== EVOLUTIONARY MEMORY & LEARNED PATTERNS ==="])
        if memory_context.project_memories:
            prompt_parts.append("Project constraints:")
            for rec in memory_context.project_memories[:3]:
                prompt_parts.append(f"  - {rec.content}")
        if memory_context.semantic_memories:
            prompt_parts.append("Proven optimization patterns:")
            for rec in memory_context.semantic_memories[:3]:
                prompt_parts.append(f"  - {rec.content}")

    # Include previous failure lessons
    if previous_failures:
        prompt_parts.extend([
            "",
            "=== PREVIOUS GENERATION FAILURES (AVOID THESE MISTAKES) ===",
        ])
        for fail in previous_failures[:5]:
            prompt_parts.append(f"  - {fail}")

    # Include target source code
    prompt_parts.extend([
        "",
        "=== ORIGINAL SOURCE CODE ===",
        f"```{language}",
        source_code.strip(),
        "```",
        "",
        "=== OUTPUT FORMAT ===",
        "Respond ONLY with a valid JSON object matching this schema:",
        "```json",
        "{",
        '  "candidates": [',
        "    {",
        '      "source_code": "<complete python code>",',
        '      "strategy": "algorithmic | caching | loop_optimization | memory_reduction | redundancy_elimination | general",',
        '      "explanation": "<brief explanation of what was changed>",',
        '      "expected_improvement": "<expected speed/memory gain>",',
        '      "potential_risks": "<edge cases or trade-offs>"',
        "    }",
        "  ]",
        "}",
        "```",
    ])

    return "\n".join(prompt_parts)


def build_explanation_prompt(original: str, candidate: str, language: str) -> str:
    """Build prompt explaining the difference between original and candidate."""
    return f"""Compare the original code and the optimized candidate implementation in {language}.
Explain the key architectural and algorithmic changes, why they yield performance improvements, and any tradeoffs.

Original Code:
```{language}
{original}
```

Optimized Candidate:
```{language}
{candidate}
```
"""


def build_experiment_summary_prompt(experiment_summary: dict) -> str:
    """Build prompt for generating a human-readable summary of experiment results."""
    return f"""Summarize the results of this MUTAGEN evolutionary optimization experiment in 2-3 concise paragraphs:

Experiment Details:
{json.dumps(experiment_summary, indent=2, default=str)}
"""
