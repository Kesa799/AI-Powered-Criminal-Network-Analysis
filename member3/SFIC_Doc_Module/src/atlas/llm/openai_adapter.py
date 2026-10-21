"""OpenAI structured output adapter implementing LlmClientPort.

Uses OpenAI SDK 3.29.0 structured outputs (`response_format={'type': 'json_schema', ...}`)
with temperature=0, response validation, secret-safe error mapping, and retry policies.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import openai
from openai import OpenAI

from atlas.contracts.model_schema import MODEL_SCHEMA, validate_model_output
from atlas.errors import ProviderError, SchemaViolationError
from atlas.llm.pacing import RateLimiter, parse_retry_after
from atlas.llm.retry import (
    AuthError,
    ConnectionError,
    InvalidJsonError,
    QuotaExceededError,
    RateLimitError,
    RefusalError,
    ServerError,
    TimeoutError,
    TruncatedOutputError,
    execute_with_retry,
)
from atlas.ports.llm import LlmClientPort

logger = logging.getLogger(__name__)

# A daily token budget is reported differently from a per-minute rate limit:
# the provider refuses with a body that names the daily window, and the wait
# is typically many minutes rather than seconds.
_DAILY_QUOTA_MARKERS = ("tokens per day", "(tpd)")


def _error_body_text(exc: Exception) -> str:
    """Return the provider's error body as text, without raising."""
    body = getattr(exc, "body", None)
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        try:
            return json.dumps(body)
        except (TypeError, ValueError):
            return str(body)
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            return str(getattr(response, "text", "") or "")
        except Exception:  # pragma: no cover - defensive
            return ""
    return ""


def _is_daily_quota(body: str) -> bool:
    """True when the refusal is an exhausted daily token budget."""
    low = body.lower()
    return any(marker in low for marker in _DAILY_QUOTA_MARKERS)


class OpenAiAdapter(LlmClientPort):
    """Adapter for OpenAI models with strict schema structured outputs."""

    # This adapter owns its retry loop, so callers must not wrap it again.
    handles_retries = True

    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        max_attempts: int = 3,
        client: OpenAI | None = None,
        base_url: str | None = None,
        provider_override: str | None = None,
        rate_limiter: RateLimiter | None = None,
        max_completion_tokens: int | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("api_key must be non-empty")
        self._model_name = model_name
        self._temperature = temperature
        self._timeout_s = timeout_s
        self._max_attempts = max_attempts
        self._provider_name = provider_override or "openai"
        self._rate_limiter = rate_limiter
        self._max_completion_tokens = max_completion_tokens
        if client is not None:
            self._client = client
        elif base_url:
            # max_retries=0: this adapter owns its own retry loop, and that loop is
            # paced by the rate limiter. Letting the SDK retry underneath would
            # burst extra requests past the configured request budget and turn a
            # transient 429 into a hard failure.
            self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0)
        else:
            self._client = OpenAI(api_key=api_key, timeout=timeout_s, max_retries=0)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def _call_raw(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Perform single API call and return validated dictionary or raise categorized errors."""
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
        effective_schema = schema if schema else MODEL_SCHEMA
        request_kwargs: dict[str, Any] = {}
        if self._max_completion_tokens and self._max_completion_tokens > 0:
            request_kwargs["max_completion_tokens"] = self._max_completion_tokens
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "model_output",
                        "strict": True,
                        "schema": effective_schema,
                    },
                },
                temperature=self._temperature,
                **request_kwargs,
            )
        except openai.AuthenticationError:
            raise AuthError("Authentication failed for OpenAI API (401). Check credentials.") from None
        except openai.PermissionDeniedError:
            raise AuthError("Permission denied for OpenAI API (403). Check credentials.") from None
        except openai.RateLimitError as exc:
            retry_after: float | None = None
            if hasattr(exc, "response") and exc.response is not None and hasattr(exc.response, "headers"):
                headers = exc.response.headers
                candidates: list[float] = []
                # `retry-after` is the provider's own hint, but it can be shorter
                # than the budget that actually blocked the request. The token
                # window header says when the token budget refills, so wait for
                # whichever of the two is longer.
                #
                # `x-ratelimit-reset-requests` is deliberately not used: it is the
                # horizon of the request-count sliding window (minutes away even
                # when the request budget is not what blocked the call).
                for header_name in ("retry-after", "x-ratelimit-reset-tokens"):
                    value = parse_retry_after(headers.get(header_name))
                    if value is not None:
                        candidates.append(value)
                if candidates:
                    retry_after = max(candidates)
                # Rate-limit headers carry no secrets, and they are the only way to
                # tell which budget was exhausted: the per-minute token window and
                # the per-day token budget need very different responses from an
                # operator.
                budget = {
                    key: value
                    for key, value in headers.items()
                    if key.lower().startswith(("x-ratelimit", "retry-after"))
                }
                logger.warning(
                    "LLM rate limit hit: provider=%s model=%s wait_s=%s headers=%s",
                    self._provider_name,
                    self._model_name,
                    retry_after,
                    budget,
                )
                body = _error_body_text(exc)
                if _is_daily_quota(body):
                    # The account's daily token budget is spent. Waiting the
                    # per-minute hint cannot help, and retrying burns the whole
                    # attempt budget for a refusal that is certain to repeat.
                    logger.error(
                        "Provider daily token budget exhausted: provider=%s model=%s wait_s=%s",
                        self._provider_name,
                        self._model_name,
                        retry_after,
                    )
                    raise QuotaExceededError(
                        f"Provider daily token budget exhausted (tokens per day); retry after {retry_after}s",
                        retry_after=retry_after,
                    ) from None
            if self._rate_limiter is not None:
                self._rate_limiter.notify_retry_after(retry_after)
            raise RateLimitError("OpenAI rate limit exceeded (429)", retry_after=retry_after) from None
        except openai.InternalServerError:
            raise ServerError("OpenAI server error (500)") from None
        except openai.APITimeoutError:
            raise TimeoutError("OpenAI request timed out") from None
        except openai.APIConnectionError:
            raise ConnectionError("OpenAI network connection failed") from None
        except openai.LengthFinishReasonError:
            raise TruncatedOutputError("OpenAI output truncated (length finish)") from None
        except openai.ContentFilterFinishReasonError:
            raise RefusalError("OpenAI request blocked by safety filter") from None
        except openai.APIStatusError as exc:
            code = getattr(exc, "status_code", None)
            if code in (401, 403):
                raise AuthError("Authentication/authorization failed for OpenAI API (401/403).") from None
            if code == 429:
                raise RateLimitError("OpenAI rate limit exceeded (429)") from None
            if code is not None and 500 <= code < 600:
                raise ServerError(f"OpenAI server error ({code})") from None
            raise ProviderError(f"OpenAI API error with status {code}") from None
        except openai.OpenAIError as exc:
            raise ProviderError(f"OpenAI client error: {type(exc).__name__}") from None

        if not response.choices:
            raise ProviderError("OpenAI returned no choices in response")

        usage = getattr(response, "usage", None)
        if usage is not None:
            # Token counts only - never the prompt or the completion. On a tier
            # with a daily token budget this is the number an operator needs to
            # decide whether the next document is affordable.
            logger.info(
                "LLM call usage: provider=%s model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                self._provider_name,
                self._model_name,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
                getattr(usage, "total_tokens", None),
            )

        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            raise TruncatedOutputError("OpenAI output truncated (length finish)")
        if finish_reason == "content_filter":
            raise RefusalError("OpenAI content filter blocked response")

        message = choice.message
        if getattr(message, "refusal", None):
            raise RefusalError("OpenAI refused to generate response")

        content = message.content
        if not content:
            raise InvalidJsonError("OpenAI returned empty message content")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise InvalidJsonError(f"Failed to parse OpenAI response as JSON: {exc}") from exc

        try:
            return validate_model_output(parsed)
        except ValueError as exc:
            raise SchemaViolationError(f"OpenAI response violated schema: {exc}") from exc

    def extract(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Perform schema-constrained extraction with Section 5.9 retries."""
        return execute_with_retry(
            lambda: self._call_raw(system, user, schema),
            max_attempts=self._max_attempts,
        )


__all__ = ["OpenAiAdapter"]
