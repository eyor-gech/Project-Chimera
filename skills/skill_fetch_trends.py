"""Skill 1 - Trend Discovery (Trend Research Agent).

Spec references
---------------
* ``specs/technical.md``  -> "Trend Discovery API" (canonical contract)
* ``specs/functional.md`` -> FR-1, FR-2, FR-3
* ``skills/README.md``    -> skill input/output contract
* ``specs/_meta.md``      -> "Skills must be stateless, deterministic"

Contract (v1.1 - superset of the canonical spec and the demo contract)
---------------------------------------------------------------------
``fetch_trends(platform: str, limit: int = 3) -> list[dict]``

Each ``Trend`` object carries the canonical spec fields **and** the richer
demo fields, so a single object satisfies both contracts at once:

    trend_id    str    stable, content-derived id (uuid5)   [spec + demo]
    title       str    human-readable topic title           [spec]
    topic       str    topic label, mirrors ``title``       [demo]
    timestamp   str    ISO 8601, deterministic per trend    [spec]
    score       float  ranking score in [0.0, 1.0]          [spec]
    volume      int    relative search-volume proxy         [demo]
    category    str    topical category                     [demo]
    platform    str    source platform                      [spec DB schema]
    context     str    extracted article + top comments     [demo, v1.2]
    source_url  str    linked source URL, if any            [demo, v1.2]

Source grounding (v1.2)
-----------------------
When ``use_real_api=True`` the skill reads each story's linked article and its
top comments through :mod:`runtime.source_reader` and attaches them as
``context``, so the generator can analyse the source instead of restating the
headline. The offline catalogue leaves ``context`` empty and stays deterministic.

Determinism
-----------
The offline path performs no I/O, no network call, no clock read and no RNG.
Trends come from a fixed per-platform catalogue, so the same
``(platform, limit)`` always yields identical output. This satisfies the
determinism constraint in ``specs/_meta.md`` and the idempotency guideline in
``skills/README.md``. The live path (``use_real_api=True``) is inherently
network-bound and therefore not deterministic.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests

from runtime.source_reader import build_source_context

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: Platforms approved by ``specs/technical.md`` -> "Trend Discovery API".
SUPPORTED_PLATFORMS: tuple = ("YouTube", "Twitter", "Instagram")

#: Upper bound on ``limit`` per ``specs/technical.md`` ("limit (integer,
#: optional): maximum 50").
MAX_LIMIT: int = 50

#: Namespace for stable ``uuid5`` trend ids (uuid.NAMESPACE_URL is used so the
#: ids are reproducible across processes and machines).
_TREND_NAMESPACE = uuid.UUID("6f1d2f4e-9c1a-5f2b-8c7d-0a1b2c3d4e5f")

#: Fixed reference point for trend timestamps. A constant (rather than
#: ``datetime.now()``) is what keeps this skill deterministic, as required by
#: ``specs/_meta.md``.
_REFERENCE_EPOCH = datetime(2026, 2, 4, 9, 0, 0, tzinfo=timezone.utc)

#: Deterministic mock catalogue, keyed by platform. This is the seam where a
#: real provider (YouTube Data API / X trends / Instagram Graph) is queried in
#: production; the contract stays identical.
_TREND_CATALOGUE: Dict[str, List[Dict[str, Any]]] = {
    "YouTube": [
        {"title": "AI Agent Workflows", "score": 0.94, "volume": 184000, "category": "Technology"},
        {"title": "Open Source LLM Runtimes", "score": 0.89, "volume": 132500, "category": "Technology"},
        {"title": "Creator Economy Deep Dives", "score": 0.81, "volume": 98200, "category": "Business"},
        {"title": "Spec Driven Development", "score": 0.76, "volume": 74900, "category": "Software"},
        {"title": "Container Native Testing", "score": 0.72, "volume": 61300, "category": "Software"},
        {"title": "Multimodal Search Reels", "score": 0.68, "volume": 55700, "category": "Technology"},
        {"title": "Autonomous Influencer Systems", "score": 0.63, "volume": 48100, "category": "AI"},
        {"title": "Governance Guardrails", "score": 0.59, "volume": 39400, "category": "Policy"},
    ],
    "Twitter": [
        {"title": "Agent Swarm Coordination", "score": 0.93, "volume": 211000, "category": "AI"},
        {"title": "MCP Server Ecosystem", "score": 0.88, "volume": 168400, "category": "Technology"},
        {"title": "Vector Database Wars", "score": 0.84, "volume": 143900, "category": "Technology"},
        {"title": "Human In The Loop Patterns", "score": 0.78, "volume": 119600, "category": "AI"},
        {"title": "Prompt Injection Defences", "score": 0.71, "volume": 92800, "category": "Security"},
        {"title": "Edge Inference Benchmarks", "score": 0.66, "volume": 77200, "category": "Hardware"},
        {"title": "OpenClaw Integration Notes", "score": 0.61, "volume": 58500, "category": "AI"},
        {"title": "Typed Contracts With Pydantic", "score": 0.57, "volume": 44100, "category": "Software"},
    ],
    "Instagram": [
        {"title": "Behind The Build Vlogs", "score": 0.92, "volume": 196700, "category": "Lifestyle"},
        {"title": "Creator Burnout Talk", "score": 0.87, "volume": 154300, "category": "Lifestyle"},
        {"title": "AI Avatar Experiments", "score": 0.83, "volume": 137100, "category": "AI"},
        {"title": "Studio Setup Tours", "score": 0.77, "volume": 105900, "category": "Lifestyle"},
        {"title": "Reels Format Deep Dive", "score": 0.70, "volume": 88600, "category": "Creator"},
        {"title": "Brand Safety Checklist", "score": 0.64, "volume": 66200, "category": "Marketing"},
        {"title": "Short Form Monetisation", "score": 0.60, "volume": 52400, "category": "Business"},
        {"title": "Day In The Life Automation", "score": 0.54, "volume": 41800, "category": "Lifestyle"},
    ],
}


class TrendDiscoveryError(ValueError):
    """Raised for spec-defined discovery failures (``specs/technical.md``).

    The ``code`` attribute carries the spec error identifier so the
    orchestrator can log ``INVALID_PLATFORM`` / ``INVALID_LIMIT`` for audit
    (FR-14) instead of propagating an opaque ``ValueError``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _validate(platform: str, limit: int) -> None:
    """Validate inputs against ``specs/technical.md`` before any work.

    Halt-on-invalid-input is mandated by FR-13: Chimera must halt and request
    clarification rather than proceed on an assumption.

    Raises:
        TrendDiscoveryError: with code ``INVALID_PLATFORM`` or ``INVALID_LIMIT``.
    """
    if not isinstance(platform, str) or platform not in SUPPORTED_PLATFORMS:
        raise TrendDiscoveryError(
            "INVALID_PLATFORM",
            "Unsupported platform {!r}. Expected one of: {}.".format(
                platform, ", ".join(SUPPORTED_PLATFORMS)
            ),
        )

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TrendDiscoveryError(
            "INVALID_LIMIT", "limit must be an int, got {!r}.".format(type(limit).__name__)
        )

    if limit < 0:
        raise TrendDiscoveryError("INVALID_LIMIT", "limit must be >= 0, got {}.".format(limit))

    if limit > MAX_LIMIT:
        raise TrendDiscoveryError(
            "INVALID_LIMIT", "limit must be <= {} per spec, got {}.".format(MAX_LIMIT, limit)
        )


def _build_trend_id(platform: str, title: str) -> str:
    """Return a stable, content-derived trend id.

    Deriving the id from ``platform + title`` (instead of a counter or the
    clock) makes the skill idempotent: the same trend always maps to the same
    primary key, which is what the ``Trends`` table in
    ``specs/technical.md`` expects.
    """
    digest = hashlib.sha256("{}::{}".format(platform, title).encode("utf-8")).hexdigest()
    return str(uuid.uuid5(_TREND_NAMESPACE, digest))


def _build_timestamp(rank: int) -> str:
    """Return a deterministic ISO 8601 timestamp for the trend at ``rank``.

    Ties the trend to the fixed reference epoch with a deterministic offset so
    the catalogue simulates a plausible recency ordering without reading the
    system clock.
    """
    moment = _REFERENCE_EPOCH - timedelta(hours=rank * 2)
    return moment.isoformat()


def _to_trend(record: Dict[str, Any], platform: str, rank: int) -> Dict[str, Any]:
    """Project one catalogue record onto the full Trend contract."""
    title = record["title"]
    return {
        # Canonical spec fields (specs/technical.md -> Trend Discovery API)
        "trend_id": _build_trend_id(platform, title),
        "title": title,
        "timestamp": _build_timestamp(rank),
        "score": round(float(record["score"]), 2),
        "platform": platform,
        # Demo-facing enrichment (same object, additive keys)
        "topic": title,
        "volume": int(record["volume"]),
        "category": record["category"],
        # Source grounding (v1.2, additive; empty for the offline catalogue)
        "context": "",
        "source_url": "",
    }


# --------------------------------------------------------------------------
# Skill entry point
# --------------------------------------------------------------------------

def fetch_trends(platform: str, limit: int = 3, use_real_api: bool = False) -> List[Dict[str, Any]]:
    """Fetch trending topics for an approved platform (FR-1, FR-2).

    Args:
        platform: One of ``YouTube``, ``Twitter``, ``Instagram``.
        limit: Maximum number of trends to return (0-50, default 3).
        use_real_api: Whether to fetch real live trends (Hacker News) or use mock catalogue.

    Returns:
        A list of ``Trend`` dicts ordered by descending ``score`` (FR-2:
        normalized and scored so trends can be ranked and compared). Each item
        contains ``trend_id``, ``title``, ``topic``, ``timestamp``, ``score``,
        ``volume``, ``category`` and ``platform``. An empty list is returned
        for ``limit=0`` or when the platform catalogue is exhausted.

    Raises:
        TrendDiscoveryError: ``INVALID_PLATFORM`` or ``INVALID_LIMIT`` when the
            inputs violate ``specs/technical.md`` (FR-13: halt, do not assume).

    Example:
        >>> trends = fetch_trends(platform="YouTube", limit=2)
        >>> trends[0]["topic"]
        'AI Agent Workflows'
    """
    _validate(platform, limit)

    if limit == 0:
        return []

    if use_real_api:
        try:
            res = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10)
            res.raise_for_status()
            story_ids = res.json()[:limit]
            real_trends = []
            for i, sid in enumerate(story_ids):
                item_res = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=10)
                item_res.raise_for_status()
                item = item_res.json()
                title = item.get("title", f"Trending Topic {i}")
                score_val = item.get("score", 100)
                norm_score = max(0.5, 1.0 - (i * 0.05))
                source = build_source_context(item)
                real_trends.append({
                    "trend_id": _build_trend_id(platform, title),
                    "title": title,
                    "timestamp": _build_timestamp(i),
                    "score": round(norm_score, 2),
                    "platform": platform,
                    "topic": title,
                    "volume": score_val * 1000,
                    "category": "Technology",
                    # v1.2: read the linked article and top comments so
                    # generation is grounded in the source, not the title alone
                    "context": source["context"],
                    "source_url": source["source_url"],
                })
            return real_trends
        except Exception as e:
            print(f"Warning: Real API failed ({e}), falling back to mock catalogue.")

    catalogue = _TREND_CATALOGUE[platform]
    selected = sorted(catalogue, key=lambda item: item["score"], reverse=True)[:limit]
    return [_to_trend(record, platform, rank) for rank, record in enumerate(selected)]


def resolve_trend(platform: str, trend_id: str) -> Optional[Dict[str, Any]]:
    """Look up a single trend by id, or return ``None`` if it is unknown.

    Shared lookup used by :mod:`skills.skill_generate_content` so that the spec
    signature ``generate_content(trend_id, platform)`` can resolve its own topic
    without the caller re-fetching the trend list. Stays stateless: the
    catalogue is the only state consulted, and the result is a fresh dict.
    """
    _validate(platform, 1)

    for rank, record in enumerate(_TREND_CATALOGUE[platform]):
        trend = _to_trend(record, platform, rank)
        if trend["trend_id"] == trend_id:
            return trend
    return None
