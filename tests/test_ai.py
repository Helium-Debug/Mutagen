"""
Tests for AI providers, prompt generation, and output parsing.
"""

import pytest

from mutagen.ai.fake_provider import FakeProvider
from mutagen.ai.output_parser import parse_mutation_response, _extract_json
from mutagen.analysis.python_analyzer import PythonAnalyzer
from mutagen.exceptions import MutagenAIError
from mutagen.schemas import OptimizationObjective, MutationStrategy


def test_fake_provider_generates_mutations(sample_python_code):
    analyzer = PythonAnalyzer()
    analysis = analyzer.analyze(sample_python_code, "test.py")
    
    provider = FakeProvider()
    response = provider.generate_mutations(
        source_code=sample_python_code,
        language="python",
        analysis=analysis,
        objective=OptimizationObjective.SPEED,
        candidate_count=3,
    )
    
    assert len(response.candidates) == 3
    for candidate in response.candidates:
        assert candidate.source_code != ""
        assert candidate.content_hash != ""
        assert candidate.candidate_id.startswith("mut-")


def test_output_parser_markdown_code_fence():
    raw_ai_text = """
Here are your optimized candidates:

```json
{
  "candidates": [
    {
      "source_code": "def fast_sum(n): return sum(n)",
      "strategy": "vectorization",
      "explanation": "Built-in sum is implemented in C",
      "expected_improvement": "5x faster"
    }
  ]
}
```
Hope this helps!
"""
    response = parse_mutation_response(raw_ai_text, model_id="test-model")
    assert len(response.candidates) == 1
    cand = response.candidates[0]
    assert cand.source_code == "def fast_sum(n): return sum(n)"
    assert cand.strategy == MutationStrategy.GENERAL
    assert "Built-in" in cand.explanation


def test_output_parser_invalid_json():
    with pytest.raises(MutagenAIError):
        parse_mutation_response("Just some non-JSON text from LLM")


def test_output_parser_salvage_truncated_json():
    raw_ai_text = """Here is the response:
```json
{
  "candidates": [
    {
      "source_code": "def fast_sum(n): return sum(n)",
      "strategy": "algorithmic",
      "explanation": "Built-in sum is fast",
      "expected_improvement": "5x faster"
    },
    {
      "source_code": "def incomplete_cand(
"""
    response = parse_mutation_response(raw_ai_text, model_id="test-model")
    assert len(response.candidates) == 1
    assert response.candidates[0].source_code == "def fast_sum(n): return sum(n)"


def test_groq_extract_failed_generation():
    from mutagen.ai.groq_provider import GroqProvider

    class MockGroqError(Exception):
        def __init__(self, body):
            self.body = body
            super().__init__(str(body))

    err = MockGroqError({
        "error": {
            "message": "Failed to generate JSON",
            "code": "json_validate_failed",
            "failed_generation": '{"candidates": [{"source_code": "x = 1", "strategy": "general"}]}',
        }
    })
    extracted = GroqProvider._extract_failed_generation(err)
    assert extracted is not None
    assert "x = 1" in extracted

