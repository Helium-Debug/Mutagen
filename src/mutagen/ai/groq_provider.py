"""
Groq AI provider for MUTAGEN.

Implements the AIProviderBase interface using the Groq Python SDK.
Provides ultra-fast mutation generation and reasoning capabilities.
"""

from __future__ import annotations

import time
from typing import Optional

from mutagen.ai.base import AIProviderBase
from mutagen.ai.output_parser import parse_mutation_response, _extract_json
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

logger = get_logger("ai.groq")

# Retry config
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 45.0
REQUEST_TIMEOUT = 120  # seconds


class GroqProvider(AIProviderBase):
    """
    Groq AI provider using LLaMA 3.3 / Mixtral / DeepSeek via Groq SDK.
    """

    def __init__(self):
        settings = get_settings()
        self._model_id = settings.ai_model or "llama-3.3-70b-versatile"
        self._api_key = settings.groq_api_key
        self._client = None
        self._model_max_tokens: Optional[int] = None

    def _get_client(self):
        """Lazily initialize the Groq client."""
        if self._client is None:
            if not self._api_key:
                raise MutagenAIError(
                    "Groq API key not configured. Set GROQ_API_KEY in your environment or .env file."
                )
            try:
                from groq import Groq
                self._client = Groq(api_key=self._api_key, timeout=REQUEST_TIMEOUT)
            except ImportError:
                raise MutagenAIError(
                    "groq package not installed. Install with: pip install groq"
                )
            except Exception as e:
                raise MutagenAIError(f"Failed to initialize Groq client: {e}")
        return self._client

    def _resolve_max_tokens(self, operation: str, candidate_count: int = 4) -> int:
        """Resolve maximum completion tokens for the current operation and model."""
        if operation != "generate_mutations":
            return 4096

        settings = get_settings()
        if settings.groq_max_tokens:
            return settings.groq_max_tokens

        # Capped at 3600 so a full file candidate can finish without truncation,
        # while keeping prompt (~2600) + completion (3600) = 6200 <= 8000 TPM limit
        return 3600

    @staticmethod
    def _extract_failed_generation(error: Exception) -> Optional[str]:
        """Extract failed_generation content from Groq BadRequestError if present."""
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            err = body.get("error", {})
            if isinstance(err, dict) and "failed_generation" in err:
                return err["failed_generation"]

        response = getattr(error, "response", None)
        if response and hasattr(response, "json"):
            try:
                data = response.json()
                if isinstance(data, dict):
                    err = data.get("error", {})
                    if isinstance(err, dict) and "failed_generation" in err:
                        return err["failed_generation"]
            except Exception:
                pass

        err_str = str(error)
        if "'failed_generation':" in err_str:
            idx = err_str.find("'failed_generation': '")
            if idx != -1:
                start = idx + len("'failed_generation': '")
                end = err_str.rfind("'")
                if end > start:
                    raw = err_str[start:end]
                    try:
                        return raw.encode("utf-8").decode("unicode_escape")
                    except Exception:
                        return raw
        return None

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
        """Generate mutation candidates using Groq."""
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
            "You are an expert compiler and evolutionary algorithm engineer for MUTAGEN. "
            "Respond ONLY with the requested valid JSON object containing mutation candidates. "
            "Do not include any prose outside the JSON or code fence."
        )

        raw_response, usage = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="generate_mutations",
            candidate_count=candidate_count,
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
            raise MutagenAIError(f"Failed to parse Groq response: {e}")

        if not response.candidates:
            raise MutagenAIError(
                "Groq returned no valid candidates. "
                "The model response could not be parsed into valid mutation candidates."
            )

        logger.info(
            f"Generated {len(response.candidates)} candidates via Groq ({self._model_id})"
        )
        return response

    def explain_change(
        self,
        original: str,
        candidate: str,
        language: str,
    ) -> str:
        """Generate an explanation of changes between original and candidate."""
        prompt = build_explanation_prompt(original, candidate, language)
        system_instruction = "You are a senior code reviewer. Explain the optimizations clearly and concisely."
        response_text, _ = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="explain_change",
        )
        return response_text

    def summarize_experiment(self, experiment_summary: dict) -> str:
        """Generate a summary of experiment results."""
        prompt = build_experiment_summary_prompt(experiment_summary)
        system_instruction = "You are an automated engineering reporting system. Provide a concise technical summary."
        response_text, _ = self._call_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            operation="summarize_experiment",
        )
        return response_text

    def check_availability(self) -> tuple[bool, str]:
        """Check if Groq API is available and key is valid."""
        try:
            client = self._get_client()
            client.models.list()
            return True, f"Groq API reachable, model: {self._model_id}"
        except MutagenAIError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Groq check failed: {e}"

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def model_id(self) -> str:
        return self._model_id

    @staticmethod
    def _get_retry_delay(error: Exception, attempt: int) -> float:
        """Extract retry wait time from headers or apply progressive TPM backoff."""
        response = getattr(error, "response", None)
        if response and hasattr(response, "headers"):
            headers = response.headers
            ra = headers.get("retry-after")
            if ra:
                try:
                    return float(ra) + 2.0
                except (ValueError, TypeError):
                    pass
            rt = headers.get("x-ratelimit-reset-tokens")
            if rt:
                try:
                    if rt.endswith("ms"):
                        return (float(rt[:-2]) / 1000.0) + 2.0
                    elif rt.endswith("s") and "m" not in rt:
                        return float(rt[:-1]) + 2.0
                    elif "m" in rt:
                        parts = rt.split("m")
                        mins = float(parts[0])
                        secs = float(parts[1].rstrip("s")) if parts[1] else 0.0
                        return (mins * 60.0 + secs) + 2.0
                except Exception:
                    pass

        # Progressive backoff for sliding TPM windows
        tpm_backoffs = [25.0, 35.0, 45.0, 60.0, 60.0]
        idx = min(attempt - 1, len(tpm_backoffs) - 1)
        return tpm_backoffs[idx]

    def _call_with_retry(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        operation: str = "unknown",
        candidate_count: int = 4,
    ) -> tuple[str, dict]:
        """Execute a Groq API call with exponential backoff retry."""
        client = self._get_client()
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        max_tokens = self._resolve_max_tokens(operation, candidate_count)
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            start_time = time.time()
            try:
                logger.debug(
                    f"Groq API call: {operation} (attempt {attempt}/{MAX_RETRIES}, model {self._model_id})"
                )

                call_kwargs = {
                    "messages": messages,
                    "model": self._model_id,
                    "temperature": 0.4,
                    "max_completion_tokens": max_tokens,
                }
                # On attempt 1, use json_object response_format if operation is generate_mutations.
                # If an attempt fails, retry without response_format so Groq doesn't reject truncated outputs with 400.
                if operation == "generate_mutations" and attempt == 1:
                    call_kwargs["response_format"] = {"type": "json_object"}

                chat_completion = client.chat.completions.create(**call_kwargs)

                duration_ms = int((time.time() - start_time) * 1000)
                choice = chat_completion.choices[0]
                text = choice.message.content or ""

                usage_data = {}
                if chat_completion.usage:
                    usage_data = {
                        "input_tokens": chat_completion.usage.prompt_tokens,
                        "output_tokens": chat_completion.usage.completion_tokens,
                        "total_tokens": chat_completion.usage.total_tokens,
                        "duration_ms": duration_ms,
                    }

                logger.debug(
                    f"Groq API call succeeded in {duration_ms}ms, "
                    f"tokens: {usage_data.get('total_tokens', 'N/A')}"
                )

                return text, usage_data

            except Exception as e:
                last_error = e
                duration_ms = int((time.time() - start_time) * 1000)

                # Check if this error contains partial generated content from Groq that can be salvaged
                if operation == "generate_mutations":
                    failed_gen = self._extract_failed_generation(e)
                    if failed_gen:
                        extracted = _extract_json(failed_gen)
                        if (
                            extracted
                            and isinstance(extracted.get("candidates"), list)
                            and len(extracted["candidates"]) > 0
                        ):
                            logger.warning(
                                f"Groq generation hit token limit/JSON validation failure, but successfully salvaged "
                                f"{len(extracted['candidates'])} candidate(s) from failed_generation."
                            )
                            return failed_gen, {
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": 0,
                                "duration_ms": duration_ms,
                                "salvaged": True,
                            }

                logger.warning(
                    f"Groq API call failed (attempt {attempt}/{MAX_RETRIES}): {e}"
                )
                if attempt < MAX_RETRIES:
                    err_msg = str(e).lower()
                    if "rate_limit" in err_msg or "429" in err_msg or "413" in err_msg or "tpm" in err_msg:
                        wait_seconds = self._get_retry_delay(e, attempt)
                        logger.warning(
                            f"Groq token rate limit reached ({e}). Waiting {wait_seconds:.1f}s for tokens to replenish..."
                        )
                        # Adaptively reduce max_completion_tokens for next attempt to shrink requested payload
                        if max_tokens > 1500:
                            max_tokens = max(1500, int(max_tokens * 0.8))
                            logger.info(f"Reduced max_completion_tokens to {max_tokens} for next retry")
                        time.sleep(wait_seconds)
                    else:
                        backoff = min(INITIAL_BACKOFF * (2 ** (attempt - 1)), MAX_BACKOFF)
                        time.sleep(backoff)

        raise MutagenAIError(
            f"Groq API call failed after {MAX_RETRIES} attempts: {last_error}"
        )
