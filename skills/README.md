# Project Chimera — Skills Directory

## Purpose
Skills are deterministic, stateless capabilities that Chimera executes at runtime.

---

## Skill Guidelines
- Each skill must have a defined **input/output contract**.
- Skills are **idempotent** whenever possible.
- Skills do **not bypass human-in-the-loop** for high-risk tasks.
- All executions are logged via MCP.
- **Network I/O stays outside the skill core** (see `runtime/llm_client.py` and
  `runtime/source_reader.py`), so every skill remains unit-testable with no
  credentials and no network.

> Contracts below are **v1.2**. Each skill returns the canonical
> `specs/technical.md` fields **plus** additive enrichment fields, so a single
> payload satisfies both the spec and the live demo. No canonical field was
> renamed or removed.

---

## Critical Skills

### 1. skill_fetch_trends
- **Purpose:** Discover trending topics from supported platforms. (FR-1, FR-2)
- **Inputs:**
  - platform: str (YouTube / Twitter / Instagram)
  - limit: int (0–50, default 3)
  - use_real_api: bool (default false) — read live Hacker News stories
- **Outputs:** List of Trend objects
  - trend_id: str — stable, content-derived (uuid5)
  - title: str
  - timestamp: ISO 8601
  - score: float (0.0–1.0)
  - platform: str
  - topic: str
  - volume: int
  - category: str
  - context: str — analysed article + top comments (v1.2)
  - source_url: str — linked source, or the discussion URL (v1.2)
- **Ordering:** descending `score`
- **Errors:** `INVALID_PLATFORM`, `INVALID_LIMIT` (raised as `TrendDiscoveryError.code`)
- **Deterministic:** Offline path only — fixed per-platform catalogue, no I/O,
  no clock, no RNG. `use_real_api=True` is network-bound and not deterministic.
- **Source grounding (v1.2, FR-16):** on the live path each story's linked
  article and top comments are read via `runtime/source_reader.py` and attached
  as `context`, so the generator analyses the source rather than restating the
  headline. Unreadable sources degrade to an empty `context` (logged, not fatal).
- **MCP Logging:** inputs, outputs, execution time
- **Helper:** `resolve_trend(platform, trend_id)` — single-trend lookup shared
  with `skill_generate_content`

### 2. skill_generate_content
- **Purpose:** Generate platform-specific content drafts. (FR-4, FR-5, FR-6)
- **Inputs:**
  - trend_id: str
  - topic: str (optional — resolved from the trend catalogue when omitted)
  - platform: str
  - context: str (optional, v1.2 — the trend's analysed article + top
    comments; resolved from the trend when omitted)
- **Outputs:** ContentDraft object
  - draft_id: str — stable uuid5, idempotent per (trend, platform, headline)
  - trend_id: str
  - content_text: str
  - media_links: list[str]
  - platform_format_valid: bool
  - platform: str
  - topic: str
  - headline: str
  - caption: str
  - brand_safety_score: float (0.0–1.0)
  - suggested_hashtags: list[str]
  - generation_mode: str — `live-llm` | `offline-stub`
  - generated_by: str — model id or `offline-deterministic-stub`
  - grounded_on_source: bool — True only when a live draft used `context` (v1.2)
- **LLM:** OpenRouter (`https://openrouter.ai/api/v1`) via the OpenAI SDK.
  Free-first model chain, tried in order:
  1. `google/gemma-4-26b-a4b-it:free` — primary
  2. `liquid/lfm-2.5-2.6b:free`
  3. `cohere/north-mini-code:free`
  4. `openai/gpt-4o-mini` — paid safety net

  A rate-limited (HTTP 429) model is retried with exponential backoff before the
  chain advances, since free tiers are throttled aggressively. Override the
  chain with `CHIMERA_MODEL_CHAIN`. Responses are strict JSON (fence-tolerant)
  and validated with pydantic (`GeneratedDraft`).

  > Free OpenRouter keys are capped at 50 free-model requests per day. Once
  > exhausted, every call falls through to `gpt-4o-mini` and spends credits.
  > `generated_by` on each draft shows which model actually served it.
- **Source grounding (v1.2, FR-16):** when `context` is present it is appended
  to the user prompt and the model is told to base the post on that material
  without inventing facts. `grounded_on_source` reports whether it actually did.
- **Fallback:** no key / provider error / `CHIMERA_OFFLINE=1` → deterministic
  offline stub derived from the trend, so the pipeline and tests never break.
  Every fallback logs its reason, so a silent degradation is visible in the
  terminal as well as in `generation_mode`.
- **Platform limits:** headline/caption length and hashtag count clamped per
  platform (YouTube 100/5000/15, Twitter 60/280/3, Instagram 90/2200/30).
- **Deterministic:** Yes for the same input trend (offline path is pure)
- **MCP Logging:** inputs, outputs, skill execution

### 3. skill_approve_content
- **Purpose:** Human-in-the-loop content approval. (FR-7, FR-8, FR-9)
- **Inputs:**
  - draft_id: str
  - draft: dict (optional — the payload carrying `brand_safety_score`)
  - threshold: float (default 0.85)
- **Outputs:** ApprovalStatus object
  - status: str — one of `['approved', 'rejected', 'needs_review']`
  - reviewer_comments: str
  - approved: bool
  - workflow_status: str — `READY_FOR_PUBLISH` | `NEEDS_HUMAN_REVIEW`
  - reason: str
  - brand_safety_score: float (-1.0 when unknown)
  - threshold: float
  - evaluated_at: ISO 8601
- **Gate rule:** `score >= threshold` → approved; below → escalated.
  **Fail-closed:** a missing or unreadable score escalates to human review,
  because absence of evidence is not evidence of safety (`specs/_meta.md`).
- **Why `status` and `workflow_status` both exist:** `status` is pinned to the
  canonical three-value enum asserted by `tests/test_skills_interface.py`;
  `workflow_status` carries the two-state publishing value. Both come from one
  decision, so they cannot disagree.
- **Deterministic:** Yes, given a draft; the reviewer role remains human
- **MCP Logging:** inputs, outputs, approval timestamps

### (Optional future skill)
- skill_publish_content → Publishes approved drafts according to schedule
- skill_analyze_engagement → Optional analytics skill for future scaling
