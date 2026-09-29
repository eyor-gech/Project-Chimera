"""OpenRouter LLM gateway for Project Chimera.

Spec references
---------------
* ``specs/technical.md``  -> "Content Generation API" (structured draft output)
* ``specs/_meta.md``      -> "Skills must be stateless, deterministic" and
  "Ambiguity must result in a halt and request for clarification"
* ``skills/README.md``    -> "Isolate side-effects (logging, network I/O)
  outside the skill core"

Why this module exists
----------------------
``skills/skill_generate_content.py`` owns the *content contract*; this module
owns the *network side effect*. Keeping them apart means the skill can be
unit-tested with no API key and no network, which is what lets
``make test`` stay green inside Docker and in CI.

Configuration (all optional, env driven)
----------------------------------------
``OPENROUTER_API_KEY``       credential; absent => offline stub is used
``CHIMERA_OPENROUTER_BASE_URL``   default ``https://openrouter.ai/api/v1``
``CHIMERA_MODEL_CHAIN``      comma-separated models, tried in order
``CHIMERA_OFFLINE``          set to ``1`` to force the deterministic stub
``CHIMERA_LLM_TIMEOUT``      request timeout in seconds (default 45)
``CHIMERA_LLM_RETRIES``      429 retries per model before moving on (default 2)
``CHIMERA_LLM_RETRY_DELAY``  first backoff delay in seconds (default 1.5)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

#: OpenRouter exposes an OpenAI-compatible surface, so the OpenAI SDK is used
#: directly with a swapped ``base_url``.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

#: Free-tier-first model chain. Every entry is tried in order until one returns
#: valid JSON, so a single rate-limited provider never breaks the pipeline.
#:
#: The head of the chain is the project-selected model,
#: ``google/gemma-4-26b-a4b-it:free``. Free OpenRouter tiers are aggressively
#: rate-limited upstream (HTTP 429 "temporarily rate-limited upstream"), so two
#: additional free fallbacks follow, with ``openai/gpt-4o-mini`` last as a
#: paid safety net. Override the whole chain with ``CHIMERA_MODEL_CHAIN``.
#:
#: Note: ``anthropic/claude-3.5-sonnet``, named in the original brief, has been
#: retired from OpenRouter (HTTP 404 "No endpoints found") and is no longer
#: reachable.
DEFAULT_MODEL_CHAIN: Tuple[str, ...] = (
    "google/gemma-4-26b-a4b-it:free",
    "liquid/lfm-2.5-2.6b:free",
    "cohere/north-mini-code:free",
    "openai/gpt-4o-mini",
)

#: Referenced in telemetry so the demo shows which model actually answered.
OFFLINE_MODEL_LABEL = "offline-deterministic-stub"

_DEFAULT_TIMEOUT = 45.0

#: Free-tier rate limits are expected, so a 429 is retried with backoff before
#: the model is considered failed.
_DEFAULT_MAX_RATE_LIMIT_RETRIES = 2
_DEFAULT_RETRY_BASE_DELAY = 1.5


def _is_rate_limited(exc: BaseException) -> bool:
    """Return True when ``exc`` is an HTTP 429 from the provider.

    Detected by status code when available, else by message text, so it works
    across OpenAI SDK versions without importing exception classes.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status == 429:
        return True
    return "429" in str(exc) or "rate limit" in str(exc).lower()


class LLMUnavailable(RuntimeError):
    """Raised when no configured model could serve a completion.

    The caller (``skill_generate_content``) catches this and falls back to the
    deterministic offline stub, so a flaky network degrades the demo instead
    of crashing it mid-interview.
    """


def _parse_json_object(raw: str) -> Dict[str, Any]:
    """Decode a model response into a dict, tolerating Markdown fences.

    Some providers wrap JSON in a ```json fence even when
    ``response_format={"type": "json_object"}`` is requested, so the fence is
    stripped before decoding and a bare object is recovered as a last resort.

    Raises:
        ValueError: the payload is not decodable, or is not a JSON object.
    """
    text = (raw or "").strip()

    if text.startswith("```"):
        # Drop an opening ```json fence and any trailing fence.
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -len("```")].strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("response was not JSON: {!r}".format(text[:120]))
        payload = json.loads(text[start : end + 1])

    if not isinstance(payload, dict):
        raise ValueError("model returned {} instead of a JSON object".format(type(payload).__name__))
    return payload


class OpenRouterClient:
    """Thin, stateless wrapper around the OpenAI SDK pointed at OpenRouter.

    The client holds no conversation state between calls: every
    :meth:`complete_json` call is a single, self-contained request. That keeps
    the calling skill compliant with the determinism rule in
    ``specs/_meta.md`` (the *network* is inherently non-deterministic, which is
    exactly why it is isolated here and why an offline stub exists).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_chain: Optional[List[str]] = None,
        timeout: Optional[float] = None,
        max_rate_limit_retries: Optional[int] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = base_url or os.getenv("CHIMERA_OPENROUTER_BASE_URL", DEFAULT_BASE_URL)
        self.model_chain = tuple(
            model_chain
            or [m.strip() for m in os.getenv("CHIMERA_MODEL_CHAIN", "").split(",") if m.strip()]
            or list(DEFAULT_MODEL_CHAIN)
        )
        self.timeout = float(os.getenv("CHIMERA_LLM_TIMEOUT", _DEFAULT_TIMEOUT)) if timeout is None else timeout
        self.max_rate_limit_retries = (
            int(os.getenv("CHIMERA_LLM_RETRIES", _DEFAULT_MAX_RATE_LIMIT_RETRIES))
            if max_rate_limit_retries is None
            else max_rate_limit_retries
        )
        #: First backoff delay in seconds; doubles per retry.
        self.retry_base_delay = float(os.getenv("CHIMERA_LLM_RETRY_DELAY", _DEFAULT_RETRY_BASE_DELAY))

    # -- capability checks -------------------------------------------------

    @property
    def is_offline_forced(self) -> bool:
        """True when ``CHIMERA_OFFLINE=1`` short-circuits all network calls."""
        return os.getenv("CHIMERA_OFFLINE", "").strip().lower() in {"1", "true", "yes"}

    @property
    def is_available(self) -> bool:
        """True when a live call is possible (key present, offline not forced)."""
        return bool(self.api_key) and not self.is_offline_forced

    # -- request -----------------------------------------------------------

    def complete_json(self, system_prompt: str, user_prompt: str) -> Tuple[Dict[str, Any], str]:
        """Return ``(payload, model_used)`` for a strict JSON completion.

        The model chain is walked in order; the first model that returns valid
        JSON wins. A malformed response, or a rate-limited provider, is treated
        as a failure for that model so the next entry gets a turn.

        Free-tier providers return HTTP 429 readily, so a rate-limited model is
        retried up to :attr:`max_rate_limit_retries` times with exponential
        backoff before the chain moves on. This keeps the primary model in play
        instead of skipping straight to a fallback on a transient limit.

        Args:
            system_prompt: Instructions defining the output contract.
            user_prompt: The per-request content brief.

        Returns:
            ``(payload, model_used)``.

        Raises:
            LLMUnavailable: no model returned a decodable JSON object.
        """
        if not self.is_available:
            raise LLMUnavailable(
                "OpenRouter unavailable "
                "(missing OPENROUTER_API_KEY or CHIMERA_OFFLINE set)."
            )

        try:
            # Imported lazily so the module (and the whole test suite) imports
            # cleanly when the optional dependency is absent.
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise LLMUnavailable("openai package is not installed.") from exc

        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        failures: List[str] = []

        for model in self.model_chain:
            for attempt in range(self.max_rate_limit_retries + 1):
                try:
                    response = client.chat.completions.create(
                        model=model,
                        temperature=0.7,
                        max_tokens=900,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    )
                    raw = response.choices[0].message.content or ""
                    payload = _parse_json_object(raw)
                    return payload, model
                except Exception as exc:  # noqa: BLE001 - any failure is handled below
                    if _is_rate_limited(exc) and attempt < self.max_rate_limit_retries:
                        delay = self.retry_base_delay * (2 ** attempt)
                        time.sleep(delay)
                        continue
                    failures.append("{}: {}".format(model, exc))
                    break

        raise LLMUnavailable("all models failed -> " + " | ".join(failures))


def get_client() -> OpenRouterClient:
    """Return a fresh client.

    A new object per call keeps the skill stateless: no cached credentials or
    sockets are shared between invocations.
    """
    return OpenRouterClient()
