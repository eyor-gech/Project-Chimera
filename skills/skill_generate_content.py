"""Skill 2 - Content Generation (Content Generation Agent).

Spec references
---------------
* ``specs/technical.md``  -> "Content Generation API" (canonical contract)
* ``specs/functional.md`` -> FR-4, FR-5, FR-6
* ``specs/_meta.md``      -> "Skills must be stateless, deterministic"
* ``skills/README.md``    -> skill input/output contract

Contract (v1.2 - superset of the canonical spec and the demo contract)
---------------------------------------------------------------------
``generate_content(trend_id: str, topic: str | None = None, platform: str = "YouTube", context: str | None = None) -> dict``

The returned ``ContentDraft`` carries the canonical spec fields **and** the
structured LLM payload:

    draft_id                 str    stable uuid5 id              [spec]
    trend_id                 str    originating trend (FR-6)     [spec]
    content_text             str    composed body text           [spec]
    media_links              list   media references (empty here) [spec]
    platform_format_valid    bool   FR-5 constraint check        [spec]
    platform                 str    target platform              [spec DB schema]
    topic                    str    resolved topic label         [traceability]
    headline                 str    structured LLM field         [demo]
    caption                  str    structured LLM field         [demo]
    brand_safety_score       float  0.0-1.0 safety signal        [demo]
    suggested_hashtags       list   structured LLM field         [demo]
    generation_mode          str    "live-llm" | "offline-stub"   [telemetry]
    generated_by             str    model id that produced it    [telemetry]
    grounded_on_source       bool   live draft used source data  [telemetry, v1.2]

Source grounding (v1.2)
-----------------------
``context`` carries the trend's analysed article and top comments (produced by
:mod:`runtime.source_reader` and attached by ``skill_fetch_trends``). When it is
present, it is appended to the LLM prompt so the draft is based on the actual
source material, not the headline alone.

Determinism and the LLM seam
----------------------------
The LLM call is routed through :mod:`runtime.llm_client` (network I/O kept
out of the skill core, per ``skills/README.md``). When no API key is
configured, the network is unreachable, or ``CHIMERA_OFFLINE=1`` is set, the
skill degrades to a deterministic offline stub derived from the trend itself.
That keeps the demo alive under failure and lets the test suite run in Docker
and CI with no credentials.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from runtime.llm_client import OFFLINE_MODEL_LABEL, LLMUnavailable, get_client
from skills.skill_fetch_trends import (
    SUPPORTED_PLATFORMS,
    resolve_trend,
)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: Namespace for stable ``uuid5`` draft ids.
_DRAFT_NAMESPACE = uuid.UUID("9a3c1e77-4b52-4d6a-9c21-7f5e0d8b3a64")

#: Per-platform content constraints (FR-5: adapt content to platform-specific
#: format, length and tone). Mirrors the platform table in
#: ``specs/technical.md`` -> "Trend Discovery API".
PLATFORM_CONSTRAINTS: Dict[str, Dict[str, int]] = {
    "YouTube": {"headline_max": 100, "caption_max": 5000, "hashtag_max": 15},
    "Twitter": {"headline_max": 60, "caption_max": 280, "hashtag_max": 3},
    "Instagram": {"headline_max": 90, "caption_max": 2200, "hashtag_max": 30},
}

_SYSTEM_PROMPT = (
    "You are the Content Generation Agent for Project Chimera, an autonomous "
    "AI influencer system. You reply with a single raw JSON object and nothing "
    "else. Required keys: 'headline' (string), 'caption' (string), "
    "'brand_safety_score' (float between 0.0 and 1.0, where 1.0 is fully "
    "brand-safe), 'suggested_hashtags' (array of strings, each starting with "
    "'#'). Keep the voice confident, concrete and free of medical, financial or "
    "political claims. Never include real people's personal data. When source "
    "material is provided, base the post on it and never invent details the "
    "source does not support."
)

_USER_PROMPT_TEMPLATE = (
    "Write a {platform} post about the trending topic: \"{topic}\".\n"
    "Constraints: headline at most {headline_max} characters, caption at most "
    "{caption_max} characters, at most {hashtag_max} hashtags.\n"
    "Respond with JSON only, using exactly these keys: headline, caption, "
    "brand_safety_score, suggested_hashtags."
)

#: Appended to the user prompt when the trend carries analysed source material
#: (v1.2), so the draft reflects the article and top comments, not the headline.
_SOURCE_CONTEXT_TEMPLATE = (
    "\nSource material (linked article and top comments) to analyse and base "
    "the post on; do not invent facts beyond it:\n{context}\n"
)

#: Hashtags used by the offline stub, rotated deterministically by topic.
_HASHTAG_POOL: tuple = (
    "AI", "Automation", "AgenticAI", "BuildInPublic", "DevTools",
    "CreatorEconomy", "TechTrends", "OpenSource", "MCP", "Future",
)

#: Logs why a draft fell back to the offline stub, so a silent degradation is
#: visible instead of only showing up as ``generation_mode == "offline-stub"``.
_LOGGER = logging.getLogger(__name__)


class ContentGenerationError(ValueError):
    """Raised for spec-defined generation failures.

    ``code`` carries the spec error identifier for orchestrator telemetry
    (FR-14); FR-13 requires a halt rather than an assumption.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# Structured output model (pydantic)
# --------------------------------------------------------------------------

class GeneratedDraft(BaseModel):
    """Validated shape of the LLM's JSON response.

    ``specs/technical.md`` requires typed, reviewable output; validating at the
    boundary means a malformed model response becomes a governance event
    rather than a downstream ``KeyError``.
    """

    headline: str = Field(min_length=1, description="Short, platform-appropriate title.")
    caption: str = Field(default="", description="Body copy for the post.")
    brand_safety_score: float = Field(
        ge=0.0, le=1.0, description="Automated brand safety signal, 0.0-1.0."
    )
    suggested_hashtags: List[str] = Field(default_factory=list)

    @field_validator("brand_safety_score", mode="before")
    @classmethod
    def _coerce_score(cls, value: Any) -> float:
        """Normalise common LLM score formats into [0.0, 1.0].

        Models occasionally answer ``92`` (percent) or ``"0.9"`` (string).
        Clamping here keeps a live demo from failing on a formatting quirk,
        while genuinely invalid values still raise.
        """
        try:
            score = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("brand_safety_score must be numeric, got {!r}".format(value)) from exc
        if 1.0 < score <= 100.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))

    @field_validator("caption", mode="before")
    @classmethod
    def _default_caption(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("suggested_hashtags", mode="before")
    @classmethod
    def _default_hashtags(cls, value: Any) -> List[str]:
        return [] if value is None else value


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _validate_platform(platform: str) -> None:
    """Reject platforms outside the spec's approved list (FR-5, FR-13)."""
    if not isinstance(platform, str) or platform not in SUPPORTED_PLATFORMS:
        raise ContentGenerationError(
            "INVALID_PLATFORM",
            "Unsupported platform {!r}. Expected one of: {}.".format(
                platform, ", ".join(SUPPORTED_PLATFORMS)
            ),
        )


def _resolve_topic(trend_id: str, topic: Optional[str], platform: str) -> Dict[str, Any]:
    """Resolve the topic context for a trend.

    An explicit ``topic`` always wins (the caller already knows it). Otherwise
    the trend catalogue is consulted by id so ``generate_content`` can be
    called with just ``(trend_id, platform)`` as the spec signature does.
    """
    if topic:
        return {"topic": topic, "trend": None}

    trend = resolve_trend(platform, trend_id)
    if trend is not None:
        return {"topic": trend["topic"], "trend": trend}

    # Unknown trend id: still generate, but flag it for human review via the
    # conservative score produced by the offline stub.
    return {"topic": "Emerging Topic", "trend": None}


def _stable_digest(*parts: str) -> bytes:
    """Return a deterministic digest for the given parts."""
    return hashlib.sha256("::".join(parts).encode("utf-8")).digest()


def _slugify(text: str) -> str:
    """Return a lowercase, hyphenated slug used to build hashtags."""
    slug = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return slug.replace(" ", "")


def _normalise_hashtags(tags: List[str], topic: str, max_tags: int) -> List[str]:
    """Deduplicate, ``#``-prefix and cap a hashtag list (FR-5)."""
    seen: List[str] = []
    for tag in tags or []:
        cleaned = str(tag).strip().lstrip("#").strip()
        if not cleaned:
            continue
        candidate = "#" + re.sub(r"[^A-Za-z0-9_]", "", cleaned)
        if candidate != "#" and candidate not in seen:
            seen.append(candidate)
        if len(seen) == max_tags:
            break

    if not seen:
        seen = ["#" + _slugify(topic) or "#Chimera"]
    return seen


def _truncate(text: str, max_chars: int) -> str:
    """Trim text to ``max_chars`` on a word boundary where possible."""
    if len(text) <= max_chars:
        return text
    clipped = text[: max_chars - 1].rsplit(" ", 1)[0]
    return (clipped or text[: max_chars - 1]).rstrip() + "…"


def check_platform_format(platform: str, headline: str, caption: str) -> bool:
    """Return whether a draft satisfies the platform's format limits (FR-5).

    Exposed for unit tests so the format contract is verifiable without going
    through the LLM.
    """
    limits = PLATFORM_CONSTRAINTS[platform]
    return (
        0 < len(headline) <= limits["headline_max"]
        and 0 < len(caption) <= limits["caption_max"]
    )


def _adapt_to_platform(platform: str, headline: str, caption: str) -> tuple:
    """Clamp a draft to the platform's limits (FR-5).

    Returns the adapted ``(headline, caption)`` pair.
    """
    limits = PLATFORM_CONSTRAINTS[platform]
    return (
        _truncate(headline, limits["headline_max"]),
        _truncate(caption, limits["caption_max"]),
    )


def _build_draft_id(trend_id: str, platform: str, headline: str) -> str:
    """Return a stable draft id so re-running a trend is idempotent."""
    return str(uuid.uuid5(_DRAFT_NAMESPACE, "{}::{}::{}".format(trend_id, platform, headline)))


def _offline_draft(topic: str, platform: str, trend: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a deterministic draft without calling any model.

    The safety proxy follows the trend's normalised ``score`` when the trend is
    known, so a weaker trend legitimately escalates to human review - the
    offline path exercises both branches of the governance gate. Unknown trends
    fall back to a digest-derived value in the same range.
    """
    digest = _stable_digest(topic, platform)
    if trend is not None:
        safety = float(trend["score"])
    else:
        safety = 0.80 + (digest[0] / 255.0) * 0.19

    limits = PLATFORM_CONSTRAINTS[platform]
    headline = "{} on {}".format(topic, platform) if platform != "Twitter" else topic
    caption = (
        "Chimera picks up {topic} from the live trend feed. "
        "Here is the short version, what it means for creators, and what to "
        "watch next. Full breakdown in the video."
    ).format(topic=topic)
    tags = [
        "#" + _HASHTAG_POOL[(digest[index] + index) % len(_HASHTAG_POOL)]
        for index in range(3)
    ]

    return {
        "headline": _truncate(headline, limits["headline_max"]),
        "caption": _truncate(caption, limits["caption_max"]),
        "brand_safety_score": round(safety, 2),
        "suggested_hashtags": _normalise_hashtags(tags, topic, limits["hashtag_max"]),
    }


def _request_llm_draft(
    topic: str, platform: str, context: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Call the LLM and return a validated draft, or ``None`` to fall back.

    When ``context`` carries source material (v1.2), it is appended to the user
    prompt so the draft analyses the article and top comments rather than
    restating the headline.

    ``None`` is returned for every failure mode (no key, network error, model
    error, malformed JSON, validation error) so the caller can degrade to the
    offline stub without branching on exception types. Each failure is logged
    with its reason so the degradation is not silent.
    """
    client = get_client()
    if not client.is_available:
        _LOGGER.warning(
            "LLM unavailable for %r on %s; using offline stub "
            "(missing OPENROUTER_API_KEY or CHIMERA_OFFLINE is set).",
            topic, platform,
        )
        return None

    limits = PLATFORM_CONSTRAINTS[platform]
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        platform=platform,
        topic=topic,
        headline_max=limits["headline_max"],
        caption_max=limits["caption_max"],
        hashtag_max=limits["hashtag_max"],
    )
    if context:
        user_prompt += _SOURCE_CONTEXT_TEMPLATE.format(context=context)

    try:
        payload, model = client.complete_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except LLMUnavailable as exc:
        _LOGGER.warning(
            "LLM call failed for %r on %s; using offline stub: %s", topic, platform, exc
        )
        return None
    except Exception as exc:  # noqa: BLE001 - never let a provider error break the pipeline
        _LOGGER.warning(
            "Unexpected LLM error for %r on %s; using offline stub: %s", topic, platform, exc
        )
        return None

    try:
        validated = GeneratedDraft(**payload)
    except Exception as exc:  # noqa: BLE001 - malformed model output is a governance event
        _LOGGER.warning(
            "Malformed LLM draft for %r on %s; using offline stub: %s", topic, platform, exc
        )
        return None

    return {
        "headline": validated.headline,
        "caption": validated.caption,
        "brand_safety_score": validated.brand_safety_score,
        "suggested_hashtags": validated.suggested_hashtags,
        "_model": model,
    }


# --------------------------------------------------------------------------
# Skill entry point
# --------------------------------------------------------------------------

def generate_content(
    trend_id: str,
    topic: Optional[str] = None,
    platform: str = "YouTube",
    context: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a platform-specific content draft for an approved trend.

    Args:
        trend_id: Originating trend id; links the draft to its trend (FR-6).
        topic: Topic label. Optional - when omitted it is resolved from the
            trend catalogue, which lets the spec signature
            ``generate_content(trend_id, platform)`` be called unchanged.
        platform: Target platform - one of ``YouTube``, ``Twitter``,
            ``Instagram`` (FR-5).
        context: Source material (v1.2) - the trend's linked article and top
            comments. When present the LLM is instructed to analyse and ground
            the draft in it instead of restating the headline. Falls back to the
            trend's own ``context`` when omitted.

    Returns:
        A ``ContentDraft`` dict. See the module docstring for the full key
        list. ``generation_mode`` reports whether the content came from the
        live LLM (``"live-llm"``) or the deterministic offline stub
        (``"offline-stub"``), ``generated_by`` names the model, and
        ``grounded_on_source`` is True only when a live draft actually used
        source material.

    Raises:
        ContentGenerationError: ``INVALID_PLATFORM`` when the platform is not
            in the spec's approved list (FR-13: halt, do not assume).

    Example:
        >>> draft = generate_content("t-1", topic="MCP Server Ecosystem", platform="Twitter")
        >>> draft["platform_format_valid"]
        True
    """
    _validate_platform(platform)

    if not trend_id:
        raise ContentGenerationError("INVALID_TREND_ID", "trend_id must be a non-empty string.")

    topic_context = _resolve_topic(trend_id, topic, platform)
    resolved_topic: str = topic_context["topic"]
    trend: Optional[Dict[str, Any]] = topic_context["trend"]

    if not context and trend is not None:
        context = trend.get("context") or None

    live = _request_llm_draft(resolved_topic, platform, context=context)
    if live is not None:
        raw_draft = live
        generation_mode = "live-llm"
        generated_by = live["_model"]
    else:
        raw_draft = _offline_draft(resolved_topic, platform, trend)
        generation_mode = "offline-stub"
        generated_by = OFFLINE_MODEL_LABEL

    # FR-5: adapt whatever came back to the platform's format constraints.
    headline, caption = _adapt_to_platform(platform, raw_draft["headline"], raw_draft["caption"])
    hashtags = _normalise_hashtags(
        raw_draft["suggested_hashtags"],
        resolved_topic,
        PLATFORM_CONSTRAINTS[platform]["hashtag_max"],
    )

    return {
        # Canonical spec fields (specs/technical.md -> Content Generation API)
        "draft_id": _build_draft_id(trend_id, platform, headline),
        "trend_id": trend_id,
        "content_text": "{}\n\n{}".format(headline, caption).strip(),
        "media_links": [],
        "platform_format_valid": check_platform_format(platform, headline, caption),
        "platform": platform,
        # Structured LLM payload (demo contract)
        "topic": resolved_topic,
        "headline": headline,
        "caption": caption,
        "brand_safety_score": round(float(raw_draft["brand_safety_score"]), 2),
        "suggested_hashtags": hashtags,
        # Telemetry (FR-14: traceable agent actions)
        "generation_mode": generation_mode,
        "generated_by": generated_by,
        "grounded_on_source": generation_mode == "live-llm" and bool(context),
    }
