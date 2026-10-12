"""
Google Gemini AI provider for MUTAGEN.

Implements the AIProviderBase interface using the google-generativeai library.
Handles retries, timeouts, rate limiting, and response parsing.
"""

from __future__ import annotations

import time
from typing import Optional

from mutagen.ai.base import AIProviderBase
from mutagen.ai.output_parser import parse_mutation_response
from mutagen.ai.prompts import (
    build_mutation_prompt,
    build_explanation_prompt,
    build_experiment_summary_prompt,
)
from mutagen.config import get_settings
from mutagen.core.logging import get_logger
from mutagen.exceptions import MutagenAIError
from mutagen.schemas import (
    CodeAnalysis, MemoryContext, MutationResponse, OptimizationObjective,
)

logger = get_logger("ai.gemini")

# Retry config
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 30.0
REQUEST_TIMEOUT = 120  # seconds


class GeminiProvider(AIProviderBase):
    """
    Google Gemini AI provider.

    Uses the google-generativeai SDK for mutation generation.
    """

    def __init__(self):
        settings = get_settings()
        self._model_id = settings.ai_model
        self._api_key = settings.gemini_api_key
        self._client = None

    def _get_client(self):
        """Lazily initialize the Gemini client."""
        if self._client is None:
            if not self._api_key:
                raise MutagenAIError(
                    "Gemini API key not configured. Set GEMINI_API_KEY in your environment."
                )
            try:
                import google.generativeai as genai
                genai.configure(api_key=self._api_key)
                self._client = genai.GenerativeModel(self._model_id)
            except ImportError:
                raise MutagenAIError(
                    "google-generativeai package not installed. "
                    "Install with: pip install google-generativeai"
                )
            except Exception as e:
                raise MutagenAIError(f"Failed to initialize Gemini client: {e}")
        return self._client

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
        """Generate mutation candidates using Gemini."""
        prompt = build_mutation_prompt(
            source_code=source_code,
            language=language,
            analysis=analysis,
            objective=objective,
            memory_context=memory_context,
            previous_failures=previous_failures,
            candidate_count=candidate_count,
        )

        raw_response = self._call_with_retry(prompt, operation="generate_mutations")

        usage = {}
        try:
            response = parse_mutation_response(
                raw_response=raw_response,
                model_id=self._model_id,
                usage=usage,
            )
        except MutagenAIError:
            raise
        except Exception as e:
            raise MutagenAIError(f"Failed to parse Gemini response: {e}")

        if not response.candidates:
            raise MutagenAIError(
                "Gemini returned no valid candidates. "
                "The model response could not be parsed into valid mutation candidates."
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
        return self._call_with_retry(prompt, operation="explain_change")

    def summarize_experiment(self, experiment_summary: dict) -> str:
        """Generate an experiment summary for evolutionary memory."""
        prompt = build_experiment_summary_prompt(experiment_summary)
        return self._call_with_retry(prompt, operation="summarize_experiment")

    def check_availability(self) -> tuple[bool, str]:
        """Check if Gemini is configured and reachable."""
        if not self._api_key:
            return False, "Gemini API key not configured (set GEMINI_API_KEY)"

        try:
            client = self._get_client()
            # Quick test — generate minimal content
            response = client.generate_content("Say 'ok'")
            if response and response.text:
                return True, f"Gemini ({self._model_id}) is available"
            return False, f"Gemini ({self._model_id}) returned empty response"
        except Exception as e:
            return False, f"Gemini ({self._model_id}) unavailable: {e}"

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_id(self) -> str:
        return self._model_id

    def _call_with_retry(self, prompt: str, operation: str = "unknown") -> str:
        """
        Call the Gemini API with exponential backoff retry.

        Args:
            prompt: The prompt to send.
            operation: Operation name for logging.

        Returns:
            The raw text response.

        Raises:
            MutagenAIError: After all retries are exhausted.
        """
        client = self._get_client()
        last_error = None
        backoff = INITIAL_BACKOFF

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    f"Gemini {operation} attempt {attempt}/{MAX_RETRIES} "
                    f"(model={self._model_id})"
                )

                response = client.generate_content(
                    prompt,
                    generation_config={
                        "temperature": 0.7,
                        "max_output_tokens": 8192,
                    },
                )

                if response and response.text:
                    logger.info(f"Gemini {operation} succeeded on attempt {attempt}")
                    return response.text

                raise MutagenAIError(f"Gemini returned empty response for {operation}")

            except MutagenAIError:
                raise
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Gemini {operation} attempt {attempt} failed: {e}"
                )
                if attempt < MAX_RETRIES:
                    sleep_time = min(backoff, MAX_BACKOFF)
                    logger.info(f"Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    backoff *= 2

        raise MutagenAIError(
            f"Gemini {operation} failed after {MAX_RETRIES} attempts. "
            f"Last error: {last_error}"
        )
