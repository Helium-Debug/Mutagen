"""
Tests for AI providers, prompt generation, and output parsing.
"""

import json
import pytest

from mutagen.ai.fake_provider import FakeProvider
from mutagen.ai.output_parser import parse_mutation_response, _extract_json
from mutagen.analysis.python_analyzer import PythonAnalyzer
from mutagen.config import reset_settings
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


def test_output_parser_string_candidates():
    # LLMs sometimes output list of code strings or stringified JSON
    raw_ai_text = json.dumps({
        "candidates": [
            "def fast_sum(n): return sum(n)",
            json.dumps({"source_code": "def fast_prod(n): return math.prod(n)", "strategy": "caching"}),
        ]
    })
    response = parse_mutation_response(raw_ai_text, model_id="test-model")
    assert len(response.candidates) == 2
    assert "fast_sum" in response.candidates[0].source_code
    assert "fast_prod" in response.candidates[1].source_code


def test_output_parser_dict_candidates():
    # LLMs sometimes output candidates as a dictionary of candidates
    raw_ai_text = json.dumps({
        "candidates": {
            "cand1": {"source_code": "def opt1(): return 1"},
            "cand2": {"source_code": "def opt2(): return 2"},
        }
    })
    response = parse_mutation_response(raw_ai_text, model_id="test-model")
    assert len(response.candidates) == 2


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


# ── Gemma Provider Tests ─────────────────────────────────────────

def test_gemma_provider_initialization():
    from mutagen.ai.gemma_provider import GemmaProvider
    provider = GemmaProvider(base_url="http://localhost:11434", model_id="gemma2:2b")
    assert provider.provider_name == "gemma"
    assert provider.model_id == "gemma2:2b"
    assert provider.base_url == "http://localhost:11434"


def test_gemma_provider_availability_mocked(mocker):
    from mutagen.ai.gemma_provider import GemmaProvider
    provider = GemmaProvider(base_url="http://mock-server:11434", model_id="gemma2:2b")

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "gemma2:2b"}, {"name": "llama3:latest"}]
    }
    mocker.patch.object(provider._get_session(), "get", return_value=mock_resp)

    available, msg = provider.check_availability()
    assert available is True
    assert "gemma2:2b" in msg


def test_gemma_provider_availability_model_missing(mocker):
    from mutagen.ai.gemma_provider import GemmaProvider
    provider = GemmaProvider(base_url="http://mock-server:11434", model_id="nonexistent-model")

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "gemma2:2b"}]
    }
    mocker.patch.object(provider._get_session(), "get", return_value=mock_resp)

    available, msg = provider.check_availability()
    assert available is False
    assert "not in local models" in msg


def test_gemma_generate_mutations_mocked(mocker, sample_python_code):
    from mutagen.ai.gemma_provider import GemmaProvider
    from mutagen.schemas import MemoryContext, MemoryRecord, MemoryType, ProgrammingLanguage

    analyzer = PythonAnalyzer()
    analysis = analyzer.analyze(sample_python_code, "test.py")

    provider = GemmaProvider(base_url="http://mock-server:11434", model_id="gemma2:2b")

    mock_json_reply = {
        "candidates": [
            {
                "mutation_id": "mut-gemma-1",
                "target_symbol": "compute_sum",
                "description": "Replaced loop with built-in sum",
                "mutation_strategy": "algorithmic",
                "source_code": "def compute_sum(numbers: list[int]) -> int:\n    return sum(numbers)\n",
                "expected_benefit": "5x faster execution",
                "complexity_analysis": {
                    "original": "O(n) python loop",
                    "candidate": "O(n) C-level sum"
                },
                "risks": ["Integer overflow on large numbers in non-python environments"],
                "required_tests": ["test_empty_list", "test_negative_numbers"]
            }
        ]
    }

    mock_post_resp = mocker.MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "message": {"content": json.dumps(mock_json_reply)},
        "prompt_eval_count": 250,
        "eval_count": 120,
        "total_duration": 1500000000,
        "eval_duration": 1200000000,
    }
    mocker.patch.object(provider._get_session(), "post", return_value=mock_post_resp)

    mem_ctx = MemoryContext(
        project_memories=[
            MemoryRecord(
                record_id="mem-1",
                memory_type=MemoryType.PROJECT,
                language=ProgrammingLanguage.PYTHON,
                content="Preserve compute_sum function signature",
            )
        ],
        total_records=1,
    )

    response = provider.generate_mutations(
        source_code=sample_python_code,
        language="python",
        analysis=analysis,
        objective=OptimizationObjective.SPEED,
        memory_context=mem_ctx,
        previous_failures=["Candidate 1 failed: SyntaxError"],
        candidate_count=1,
    )

    assert len(response.candidates) == 1
    cand = response.candidates[0]
    assert cand.candidate_id == "mut-gemma-1"
    assert cand.target_symbol == "compute_sum"
    assert cand.strategy == MutationStrategy.ALGORITHMIC
    assert "sum(numbers)" in cand.source_code
    assert response.usage.get("total_tokens") == 370


def test_gemma_code_analysis_mocked(mocker, sample_python_code):
    from mutagen.ai.gemma_provider import GemmaProvider
    provider = GemmaProvider(base_url="http://mock-server:11434", model_id="gemma2:2b")

    mock_analysis_reply = {
        "language": "python",
        "structural_summary": {
            "functions": ["compute_sum"],
            "classes": [],
            "public_interface": ["compute_sum"],
            "external_dependencies": []
        },
        "complexity": {
            "estimated_time_complexity": "O(n)",
            "estimated_space_complexity": "O(1)",
            "bottlenecks": ["Manual accumulation loop in Python bytecode"]
        },
        "optimization_suggestions": [
            {
                "target_symbol": "compute_sum",
                "strategy": "algorithmic",
                "description": "Utilize built-in sum() implemented in C",
                "expected_impact": "speed improvement"
            }
        ],
        "correctness_invariants": [
            "Must return integer sum",
            "Must handle empty list returning 0"
        ]
    }

    mock_post_resp = mocker.MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "message": {"content": json.dumps(mock_analysis_reply)},
        "prompt_eval_count": 180,
        "eval_count": 95,
        "total_duration": 1000000000,
    }
    mocker.patch.object(provider._get_session(), "post", return_value=mock_post_resp)

    res = provider.analyze_code(
        source_code=sample_python_code,
        language="python",
        objective=OptimizationObjective.SPEED,
    )

    assert res["language"] == "python"
    assert "compute_sum" in res["structural_summary"]["functions"]
    assert len(res["optimization_suggestions"]) == 1
    assert res["usage"]["total_tokens"] == 275


def test_gemma_explain_failure_and_optimization(mocker):
    from mutagen.ai.gemma_provider import GemmaProvider
    provider = GemmaProvider(base_url="http://mock-server:11434", model_id="gemma2:2b")

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": "Root Cause: ZeroDivisionError on empty input."},
        "prompt_eval_count": 50,
        "eval_count": 20,
    }
    mocker.patch.object(provider._get_session(), "post", return_value=mock_resp)

    fail_text = provider.explain_failure(
        original="x = a / b",
        candidate="x = a // b",
        failure_reasons=["ZeroDivisionError: division by zero"],
        language="python",
    )
    assert "ZeroDivisionError" in fail_text

    mock_resp.json.return_value = {
        "message": {"content": "Optimization Analysis: Vectorized sum runs 4.2x faster."},
        "prompt_eval_count": 60,
        "eval_count": 30,
    }
    opt_text = provider.explain_optimization(
        original="total = 0\nfor x in lst: total += x",
        candidate="total = sum(lst)",
        benchmark_info={"speed_improvement": 420.0, "median_time": 0.002},
        language="python",
    )
    assert "4.2x faster" in opt_text


def test_gemma_empty_candidates_raises(mocker, sample_python_code):
    from mutagen.ai.gemma_provider import GemmaProvider
    analyzer = PythonAnalyzer()
    analysis = analyzer.analyze(sample_python_code, "test.py")

    provider = GemmaProvider(base_url="http://mock-server:11434", model_id="gemma2:2b")

    mock_post_resp = mocker.MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "message": {"content": json.dumps({"candidates": []})},
        "prompt_eval_count": 100,
        "eval_count": 10,
    }
    mocker.patch.object(provider._get_session(), "post", return_value=mock_post_resp)

    with pytest.raises(MutagenAIError, match="Gemma returned no valid candidates"):
        provider.generate_mutations(
            source_code=sample_python_code,
            language="python",
            analysis=analysis,
            objective=OptimizationObjective.SPEED,
        )


def test_gemma_openai_v1_fallback(mocker):
    from mutagen.ai.gemma_provider import GemmaProvider
    import requests

    provider = GemmaProvider(base_url="http://mock-server:11434", model_id="gemma2:2b")

    # First call to /api/chat returns 404
    mock_404 = mocker.MagicMock()
    mock_404.status_code = 404

    # Second call to /v1/chat/completions succeeds
    mock_200 = mocker.MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {
        "choices": [{"message": {"content": "Explaining diff via OpenAI format"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    session = provider._get_session()
    mocker.patch.object(session, "post", side_effect=[mock_404, mock_200])

    text = provider.explain_change("a = 1", "a = 2", "python")
    assert "OpenAI format" in text


def test_service_layer_returns_gemma_provider(monkeypatch):
    from mutagen.services import get_ai_provider
    from mutagen.ai.gemma_provider import GemmaProvider

    monkeypatch.setenv("MUTAGEN_AI_PROVIDER", "gemma")
    reset_settings()

    provider = get_ai_provider()
    assert isinstance(provider, GemmaProvider)
    assert provider.provider_name == "gemma"


def test_gemma_live_inference_if_available():
    """Optional live integration test against local Ollama if running."""
    from mutagen.ai.gemma_provider import GemmaProvider
    provider = GemmaProvider()
    available, msg = provider.check_availability()
    if not available:
        pytest.skip(f"Local Gemma model not currently available: {msg}")

    explanation = provider.explain_change(
        original="def add(a, b): return a + b",
        candidate="def add(a, b): return a + b  # optimized",
        language="python",
    )
    assert isinstance(explanation, str)
    assert len(explanation.strip()) > 0



