"""
Gemma local AI provider for MUTAGEN.

Implements the AIProviderBase interface using local inference (Ollama / OpenAI-compatible endpoint).
Provides high-performance, private, zero-external-cost code analysis, mutation generation,
optimization reasoning, and evolutionary explanation capabilities.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import requests

from mutagen.ai.base import AIProviderBase
from mutagen.ai.output_parser import parse_mutation_response, _extract_json
from mutagen.ai.prompts import (
    build_mutation_prompt,
    build_code_analysis_prompt,
    build_failure_analysis_prompt,
    build_optimization_explanation_prompt,
    build_benchmark_interpretation_prompt,
    build_explanation_prompt,
    build_experiment_summary_prompt,
)
from mutagen.config import get_settings
from mutagen.core.logging import get_logger
from mutagen.exceptions import MutagenAIError
from mutagen.schemas import (
    CodeAnalysis, MemoryContext, MutationCandidate, MutationResponse, OptimizationObjective,
)

logger = get_logger("ai.gemma")

MAX_RETRIES = 4
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 30.0
DEFAULT_TIMEOUT = 120  # seconds


class GemmaProvider(AIProviderBase):
    """
    Local Gemma provider supporting Ollama and OpenAI-compatible inference servers.
    
    Communicates over HTTP to localhost:11434 (or configured base URL) without
    requiring external cloud credentials or leaking proprietary code.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        settings = get_settings()
        self._base_url = (base_url or getattr(settings, "gemma_base_url", "http://localhost:11434")).rstrip("/")
        self._model_id = model_id or settings.ai_model or "gemma4:e4b"
        self._api_key = api_key or getattr(settings, "gemma_api_key", None)
        self._timeout = timeout or getattr(settings, "gemma_timeout", DEFAULT_TIMEOUT)
        self._num_ctx = getattr(settings, "gemma_num_ctx", 16384)
        self._max_tokens = getattr(settings, "gemma_max_tokens", 8192)
        self._session = None

    def _get_session(self) -> requests.Session:
        """Lazily initialize requests session with optional headers."""
        if self._session is None:
            self._session = requests.Session()
            if self._api_key:
                self._session.headers.update({"Authorization": f"Bearer {self._api_key}"})
            self._session.headers.update({"Content-Type": "application/json"})
        return self._session

    @property
    def provider_name(self) -> str:
        return "gemma"

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def base_url(self) -> str:
        return self._base_url

    def check_availability(self) -> tuple[bool, str]:
        """
        Check if the local Gemma inference service is running and the model is loaded.
        
        Returns:
            Tuple of (is_available, status_message).
        """
        session = self._get_session()

        # 1. Check Ollama native /api/tags
        try:
            resp = session.get(f"{self._base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                
                # Check if exact or tag-stripped model is present
                model_found = any(
                    self._model_id == m
                    or self._model_id == m.split(":")[0]
                    or m.startswith(self._model_id)
                    for m in models
                )
                if model_found:
                    return True, f"Gemma local server reachable at {self._base_url}, model '{self._model_id}' available"
                
                available_str = ", ".join(models) if models else "none"
                return (
                    False,
                    f"Gemma server at {self._base_url} is reachable, but model '{self._model_id}' is not in local models ({available_str}). "
                    f"Run: ollama pull {self._model_id}"
                )
        except requests.exceptions.RequestException:
            pass

        # 2. Check OpenAI-compatible /v1/models endpoint
        try:
            resp = session.get(f"{self._base_url}/v1/models", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id", "") for m in data.get("data", [])]
                if not models or any(self._model_id in m for m in models):
                    return True, f"Gemma endpoint reachable at {self._base_url}/v1, model '{self._model_id}'"
                return True, f"Gemma endpoint reachable at {self._base_url}/v1 (models: {', '.join(models)})"
        except requests.exceptions.RequestException:
            pass

        return False, (
            f"Cannot connect to Gemma inference server at {self._base_url}. "
            f"Ensure Ollama is running (`ollama serve`) or check GEMMA_BASE_URL."
        )

    def analyze_code(
        self,
        source_code: str,
        language: str,
        objective: OptimizationObjective = OptimizationObjective.BALANCED,
        static_context: Optional[dict] = None,
    ) -> dict:
        """
        Perform AI-assisted structural, complexity, performance bottleneck, and correctness analysis.
        """
        prompt = build_code_analysis_prompt(
            source_code=source_code,
            language=language,
            objective=objective,
            static_context=static_context,
        )
        system_instruction = (
            "You are an expert static analyzer and compiler architect for MUTAGEN. "
            "Analyze the target code and respond ONLY with a valid JSON object matching the requested schema."
        )

        raw_response, usage = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="analyze_code",
            require_json=True,
        )

        extracted = _extract_json(raw_response)
        if not extracted or not isinstance(extracted, dict):
            # Fallback to basic dictionary structure wrapping raw text if model produces unparseable JSON
            logger.warning("Could not parse structured JSON from Gemma code analysis; wrapping in standard analysis schema")
            return {
                "language": language,
                "raw_analysis": raw_response[:2000],
                "structural_summary": static_context.get("structural", {}) if static_context else {},
                "complexity": {"estimated_time_complexity": "unknown"},
                "optimization_suggestions": [],
                "correctness_invariants": [],
                "usage": usage,
            }

        extracted["usage"] = usage
        return extracted

    def generate_mutations(
        self,
        source_code: str,
        language: str,
        analysis: CodeAnalysis,
        objective: OptimizationObjective,
        memory_context: Optional[MemoryContext] = None,
        previous_failures: Optional[list[str]] = None,
        candidate_count: int = 4,
    ) -> MutationResponse:
        """
        Generate multiple distinct mutation candidates using local Gemma.
        """
        prompt = build_mutation_prompt(
            source_code=source_code,
            language=language,
            analysis=analysis,
            objective=objective,
            memory_context=memory_context,
            previous_failures=previous_failures,
            candidate_count=candidate_count,
        )

        system_instruction = (
            "You are the evolutionary mutation engine of MUTAGEN. "
            "Propose optimized, syntactically complete candidate implementations in the target language. "
            "Preserve all public function and class interfaces exactly. "
            "Respond ONLY with a valid JSON object containing the 'candidates' array. "
            "Do not output markdown explanations or lengthy thinking outside the JSON."
        )

        raw_response, usage = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="generate_mutations",
            candidate_count=candidate_count,
            require_json=True,
        )

        try:
            response = parse_mutation_response(
                raw_response=raw_response,
                model_id=self._model_id,
                usage=usage,
            )
        except MutagenAIError:
            raise
        except Exception as e:
            raise MutagenAIError(f"Failed to parse Gemma mutation response: {e}")

        if not response.candidates:
            raise MutagenAIError(
                "Gemma returned no valid candidates. "
                "The model response could not be parsed into valid mutation candidates."
            )

        logger.info(
            f"Generated {len(response.candidates)} candidates via Gemma ({self._model_id})"
        )
        return response

    def explain_change(
        self,
        original: str,
        candidate: str,
        language: str,
    ) -> str:
        """Generate a human-readable explanation of code changes."""
        prompt = build_explanation_prompt(original, candidate, language)
        system_instruction = "You are a senior compiler optimization specialist. Explain code changes concisely and accurately."
        response_text, _ = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="explain_change",
        )
        return response_text

    def explain_failure(
        self,
        original: str,
        candidate: str,
        failure_reasons: list[str],
        language: str,
    ) -> str:
        """Analyze a failed mutation or test regression."""
        prompt = build_failure_analysis_prompt(original, candidate, failure_reasons, language)
        system_instruction = "You are MUTAGEN's post-mortem analysis specialist. Diagnose why the mutation failed and extract reusable lessons."
        response_text, _ = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="explain_failure",
        )
        return response_text

    def explain_optimization(
        self,
        original: str,
        candidate: str,
        benchmark_info: dict,
        language: str,
    ) -> str:
        """Explain verified optimizations and empirical benchmark findings."""
        prompt = build_optimization_explanation_prompt(original, candidate, benchmark_info, language)
        system_instruction = "You are a performance engineering specialist. Explain verified code speedups and algorithmic improvements based on benchmark data."
        response_text, _ = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="explain_optimization",
        )
        return response_text

    def interpret_benchmark(
        self,
        benchmark_data: dict,
        baseline_data: Optional[dict] = None,
    ) -> str:
        """Interpret empirical benchmark statistics and distributions."""
        prompt = build_benchmark_interpretation_prompt(benchmark_data, baseline_data)
        system_instruction = "You are MUTAGEN's statistical performance analyst. Interpret benchmark results accurately without speculation."
        response_text, _ = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="interpret_benchmark",
        )
        return response_text

    def summarize_experiment(self, experiment_summary: dict) -> str:
        """Generate an experiment summary for evolutionary memory."""
        prompt = build_experiment_summary_prompt(experiment_summary)
        system_instruction = "You are an automated engineering reporting system. Provide a concise technical summary."
        response_text, _ = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="summarize_experiment",
        )
        return response_text

    def verify_candidate_with_usage(
        self,
        prompt: str,
        system_instruction: str = "",
    ) -> tuple[str, dict]:
        """Execute logical correctness verification reasoning on Gemma 4 and return response with token usage."""
        return self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction or "You are MUTAGEN's correctness verifier.",
            operation="logical_verification",
            require_json=True,
        )

    def verify_candidate(
        self,
        prompt: str,
        system_instruction: str = "",
    ) -> str:
        """Execute logical correctness verification reasoning on Gemma 4."""
        response_text, _ = self.verify_candidate_with_usage(prompt, system_instruction)
        return response_text

    def _call_with_retry(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        operation: str = "unknown",
        candidate_count: int = 4,
        require_json: bool = False,
    ) -> tuple[str, dict]:
        """
        Execute inference call to local Gemma server with exponential backoff.
        
        Attempts Ollama `/api/chat` first, and seamlessly falls back to `/v1/chat/completions`.
        """
        session = self._get_session()
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            start_time = time.time()
            try:
                logger.debug(
                    f"Gemma call: {operation} (attempt {attempt}/{MAX_RETRIES}, model {self._model_id})"
                )

                # Try Ollama native endpoint (/api/chat)
                payload = {
                    "model": self._model_id,
                    "messages": [],
                    "stream": False,
                    "options": {
                        "temperature": 0.5 if require_json else 0.7,
                        "repeat_penalty": 1.1,
                        "num_ctx": self._num_ctx,
                        "num_predict": self._max_tokens,
                    },
                }
                if system_instruction:
                    payload["messages"].append({"role": "system", "content": system_instruction})
                payload["messages"].append({"role": "user", "content": prompt})

                if require_json:
                    payload["format"] = "json"

                resp = session.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                    timeout=self._timeout,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    duration_ms = int((time.time() - start_time) * 1000)
                    msg_obj = data.get("message", {})
                    content = msg_obj.get("content", "")
                    thinking = msg_obj.get("thinking", "")
                    done_reason = data.get("done_reason", "")

                    # Fallback to thinking field if content is empty but JSON was emitted inside thinking
                    if not content and thinking:
                        if '"candidates"' in thinking or "{" in thinking:
                            logger.debug("Content was empty; using thinking output as JSON candidate source.")
                            content = thinking

                    # If content is still empty and output hit context limit
                    if not content and done_reason == "length":
                        raise MutagenAIError(
                            f"Model '{self._model_id}' output truncated before generating JSON (context limit reached). "
                            f"Input tokens: {data.get('prompt_eval_count')}, Generated: {data.get('eval_count')}. "
                            "Recommendation: increase GEMMA_NUM_CTX in .env to allow larger context headroom."
                        )

                    usage = {
                        "input_tokens": data.get("prompt_eval_count", 0),
                        "output_tokens": data.get("eval_count", 0),
                        "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                        "duration_ms": duration_ms,
                        "eval_duration_ms": int(data.get("eval_duration", 0) / 1_000_000),
                    }
                    logger.debug(
                        f"Gemma API call succeeded in {duration_ms}ms, tokens: {usage['total_tokens']}"
                    )
                    return content, usage
                elif resp.status_code == 404:
                    # Endpoint might be OpenAI-compatible server rather than Ollama /api/chat
                    v1_payload = {
                        "model": self._model_id,
                        "messages": [],
                        "temperature": 0.2 if require_json else 0.4,
                    }
                    if system_instruction:
                        v1_payload["messages"].append({"role": "system", "content": system_instruction})
                    v1_payload["messages"].append({"role": "user", "content": prompt})
                    if require_json:
                        v1_payload["response_format"] = {"type": "json_object"}

                    v1_resp = session.post(
                        f"{self._base_url}/v1/chat/completions",
                        json=v1_payload,
                        timeout=self._timeout,
                    )
                    v1_resp.raise_for_status()
                    data = v1_resp.json()
                    duration_ms = int((time.time() - start_time) * 1000)
                    choice = data["choices"][0]
                    content = choice["message"]["content"]
                    usage_obj = data.get("usage", {})
                    usage = {
                        "input_tokens": usage_obj.get("prompt_tokens", 0),
                        "output_tokens": usage_obj.get("completion_tokens", 0),
                        "total_tokens": usage_obj.get("total_tokens", 0),
                        "duration_ms": duration_ms,
                    }
                    return content, usage
                else:
                    error_detail = resp.text[:300] if resp.text else f"status {resp.status_code}"
                    raise requests.exceptions.HTTPError(f"Ollama /api/chat error {resp.status_code}: {error_detail}", response=resp)

            except Exception as e:
                last_error = e
                duration_ms = int((time.time() - start_time) * 1000)
                logger.warning(
                    f"Gemma API call failed (attempt {attempt}/{MAX_RETRIES}): {e}"
                )

                # If connection refused or 404/fatal auth, don't spin endlessly
                err_str = str(e).lower()
                if "connection refused" in err_str or "unauthorized" in err_str or "401" in err_str:
                    raise MutagenAIError(
                        f"Gemma service connection error at {self._base_url}: {e}. "
                        f"Ensure local inference server is running and accessible."
                    )

                if attempt < MAX_RETRIES:
                    backoff = min(INITIAL_BACKOFF * (2 ** (attempt - 1)), MAX_BACKOFF)
                    time.sleep(backoff)

        raise MutagenAIError(
            f"Gemma inference failed after {MAX_RETRIES} attempts: {last_error}"
        )
