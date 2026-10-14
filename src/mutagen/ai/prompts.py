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
        '      "mutation_id": "mut-<unique-short-id>",',
        '      "target_symbol": "<target-function-or-module>",',
        '      "description": "<what changes and why>",',
        '      "mutation_strategy": "algorithmic | data_structure | caching | loop_optimization | memory_reduction | redundancy_elimination | general",',
        '      "source_code": "<complete, runnable implementation>",',
        '      "expected_benefit": "<anticipated speedup or memory reduction>",',
        '      "complexity_analysis": {',
        '        "original": "estimated original time/space complexity",',
        '        "candidate": "estimated candidate time/space complexity"',
        '      },',
        '      "risks": ["potential semantic, precision, or performance risks"],',
        '      "required_tests": ["relevant test scenarios to guarantee correctness"]',
        "    }",
        "  ]",
        "}",
        "```",
    ])

    return "\n".join(prompt_parts)


def build_code_analysis_prompt(
    source_code: str,
    language: str,
    objective: OptimizationObjective = OptimizationObjective.BALANCED,
    static_context: Optional[dict] = None,
) -> str:
    """Build prompt for AI codebase/module analysis."""
    context_str = json.dumps(static_context or {}, indent=2) if static_context else "None provided"
    return f"""You are the code analysis engine of MUTAGEN, an evolutionary code optimization platform.
Perform a thorough, multi-dimensional analysis of the following {language.upper()} code.

Target Language: {language.upper()}
Optimization Objective: {objective.value}

Static AST Context:
{context_str}

Source Code:
```{language}
{source_code.strip()}
```

Perform:
1. Structural Analysis: Identify functions, classes, dependencies, and public API interfaces that must be preserved.
2. Complexity Analysis: Estimate time and space complexity, identify nested loops, redundant operations, or excessive allocations.
3. Performance Bottleneck Identification: Highlight specific hotspots and propose concrete algorithmic or data-structure optimizations.
4. Correctness & Invariant Analysis: Identify critical edge cases, precision requirements, and semantics that mutations must NOT break.

Respond ONLY with a valid JSON object conforming to this schema:
```json
{{
  "language": "{language}",
  "structural_summary": {{
    "functions": ["function names"],
    "classes": ["class names"],
    "public_interface": ["public symbols"],
    "external_dependencies": ["imported modules"]
  }},
  "complexity": {{
    "estimated_time_complexity": "O(...)",
    "estimated_space_complexity": "O(...)",
    "bottlenecks": ["identified computational bottlenecks"]
  }},
  "optimization_suggestions": [
    {{
      "target_symbol": "name",
      "strategy": "algorithmic | caching | loop_optimization | memory_reduction | redundancy_elimination",
      "description": "concrete optimization proposal",
      "expected_impact": "speed | memory | throughput improvement"
    }}
  ],
  "correctness_invariants": [
    "edge cases and constraints that must remain intact"
  ]
}}
```"""


def build_failure_analysis_prompt(
    original: str,
    candidate: str,
    failure_reasons: list[str],
    language: str,
) -> str:
    """Build prompt explaining a failed mutation or test regression."""
    failures_formatted = "\n".join(f"- {f}" for f in failure_reasons) if failure_reasons else "Unknown test/validation failure"
    return f"""You are MUTAGEN's post-mortem analysis engine.
A proposed code mutation in {language.upper()} failed verification tests or caused performance regressions.
Analyze why this failure occurred and extract concrete lessons for future generations.

Failure Diagnostics:
{failures_formatted}

Original Code:
```{language}
{original}
```

Mutated Candidate:
```{language}
{candidate}
```

Respond with:
1. Root Cause: Precise explanation of the semantic bug, syntax error, or performance degradation.
2. Invariant Violated: What interface, edge case, or mathematical contract was broken.
3. Evolutionary Lesson: A concise, reusable rule for future evolutionary generations to prevent similar mistakes.
"""


def build_optimization_explanation_prompt(
    original: str,
    candidate: str,
    benchmark_info: dict,
    language: str,
) -> str:
    """Build prompt explaining the verified optimizations and benchmark results."""
    bench_str = json.dumps(benchmark_info, indent=2, default=str)
    return f"""You are MUTAGEN's verification reasoning engine.
Compare the original code and the successful, verified candidate implementation in {language.upper()}.
Explain the measured optimizations based on the empirical benchmark data.

Empirical Benchmark Results:
{bench_str}

Original Code:
```{language}
{original}
```

Optimized Candidate:
```{language}
{candidate}
```

Provide a clear, technically rigorous explanation of:
1. Key algorithmic and architectural changes.
2. Why these changes resulted in the measured performance and memory differences.
3. Any trade-offs or constraints introduced by the optimization.
"""


def build_benchmark_interpretation_prompt(
    benchmark_data: dict,
    baseline_data: Optional[dict] = None,
) -> str:
    """Build prompt for interpreting benchmark statistics and distributions."""
    data = {
        "candidate_benchmark": benchmark_data,
        "baseline_benchmark": baseline_data or {},
    }
    return f"""You are MUTAGEN's statistical performance analyst.
Interpret the following empirical benchmark measurements. Distinguish measured facts from hypotheses.

Benchmark Data:
{json.dumps(data, indent=2, default=str)}

Provide a concise technical assessment covering:
1. Performance Delta: Wall-clock speedup and CPU utilization differences.
2. Memory Footprint: Peak memory allocation impact.
3. Stability: Variance, standard deviation, and measurement noise across repetitions.
4. Final Verdict: Whether the candidate represents a statistically significant improvement.
"""


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
