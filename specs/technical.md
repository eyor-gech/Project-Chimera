# Project Chimera — Technical Specification

> **Amendment log**
> - **v1.2** — Content is grounded in each trend's *source material* (linked
>   article text and top comments) instead of the headline alone (FR-16).
>   `Trend` gained `context` and `source_url`; `generate_content` gained a
>   `context` input and a `grounded_on_source` output; `fetch_trends` gained
>   the documented `use_real_api` input. All additive.
> - **v1.1** — Skill contracts extended to a **superset** shape. Each API below
>   now documents its canonical fields *plus* the additive enrichment fields
>   required by the live demonstration. No canonical field was renamed or
>   removed, so `tests/test_skills_interface.py` and
>   `tests/test_trend_fetcher.py` remain valid contracts.
> - `skill_approve_content` gained a second input (`draft`) and a second status
>   field (`workflow_status`) — see the note under Governance & Approval.

## API Contracts

### Trend Discovery API
- **Function:** `fetch_trends(platform: str, limit: int = 3, use_real_api: bool = False) -> List[Trend]`
- **Inputs:**
  - `platform` (string, required): one of `['YouTube', 'Twitter', 'Instagram']`
  - `limit` (integer, optional): 0–50, default 3
  - `use_real_api` (bool, v1.2): read live Hacker News stories instead of the
    offline catalogue. Each story's linked article and top comments are analysed
    and attached as `context`.
- **Outputs:**
  - List of `Trend` objects:
    - `trend_id` (string) — stable, content-derived (uuid5)
    - `title` (string)
    - `timestamp` (ISO 8601 string)
    - `score` (float, 0.0–1.0)
    - `platform` (string) — source platform
    - `topic` (string) — v1.1 additive; mirrors `title`
    - `volume` (integer) — v1.1 additive; relative search-volume proxy
    - `category` (string) — v1.1 additive; topical category
    - `context` (string) — v1.2 additive; analysed article + top comments used
      to ground generation. Empty when the source cannot be read.
    - `source_url` (string) — v1.2 additive; the linked source, or the
      discussion URL
  - Ordering: descending `score` (FR-2)
  - Determinism: the offline path performs no I/O, clock read or RNG; same
    inputs yield identical output. The live path is network-bound and therefore
    not deterministic.
- **Source reading (v1.2):** article/comment retrieval is isolated in
  `runtime/source_reader.py`, outside the skill core (`skills/README.md`).
  Failures degrade to an empty `context` rather than halting the run.
- **Errors:**
  - `INVALID_PLATFORM` — platform not in the approved list
  - `INVALID_LIMIT` — `limit` outside 0–50 or not an `int`

---

### Content Generation API
- **Function:** `generate_content(trend_id: str, topic: str = None, platform: str = "YouTube", context: str = None) -> ContentDraft`
- **Inputs:**
  - `trend_id` (string, required)
  - `topic` (string, optional): v1.1 additive. When omitted, resolved from the
    trend catalogue by `trend_id`, so the original two-argument call remains valid.
  - `platform` (string, required)
  - `context` (string, optional, v1.2): analysed source material for the trend
    (article text and top comments). When supplied it is appended to the LLM
    prompt so the draft analyses the source rather than the headline (FR-16).
    Falls back to the resolved trend's own `context` when omitted.
- **Outputs:**
  - `ContentDraft` object:
    - `draft_id` (string) — stable uuid5; re-running a trend is idempotent
    - `trend_id` (string)
    - `content_text` (string)
    - `media_links` (list[string])
    - `platform_format_valid` (bool)
    - `platform` (string)
    - `topic` (string) — v1.1 additive; resolved topic label
    - `headline` (string) — v1.1 additive; structured LLM field
    - `caption` (string) — v1.1 additive; structured LLM field
    - `brand_safety_score` (float, 0.0–1.0) — v1.1 additive; safety signal
    - `suggested_hashtags` (list[string]) — v1.1 additive; structured LLM field
    - `generation_mode` (string) — v1.1 additive: `live-llm` | `offline-stub`
    - `generated_by` (string) — v1.1 additive; model id or offline stub label
    - `grounded_on_source` (bool) — v1.2 additive; True only when a live draft
      actually used `context`
- **Validation:**
  - Draft must adhere to platform-specific constraints (headline/caption
    length and hashtag count are clamped per platform)
  - Content must be original; cannot reuse other agents' drafts
  - LLM output is validated against the `GeneratedDraft` schema before use;
    a malformed response is a governance event, not a downstream error

- **LLM Configuration (v1.1):**
  - Provider: OpenRouter via the OpenAI SDK
    (`base_url=https://openrouter.ai/api/v1`, key from `OPENROUTER_API_KEY`)
  - Model chain, tried in order:
    1. `google/gemma-4-26b-a4b-it:free` — primary
    2. `liquid/lfm-2.5-2.6b:free` — free fallback
    3. `cohere/north-mini-code:free` — free fallback
    4. `openai/gpt-4o-mini` — paid safety net
    Override the whole chain with `CHIMERA_MODEL_CHAIN`.
  - **Rate limiting:** free tiers return HTTP 429 readily, so a rate-limited
    model is retried with exponential backoff (`CHIMERA_LLM_RETRIES`, default 2;
    `CHIMERA_LLM_RETRY_DELAY`, default 1.5s) before the chain advances.
  - **Fail-closed telemetry:** `generated_by` records which model actually
    served the draft, so a silent fall-through to the paid model is visible in
    the run summary rather than being hidden.
  - Response format: strict JSON object (Markdown-fence tolerant)
  - **Fallback:** with no API key, on network/provider error, or when
    `CHIMERA_OFFLINE=1`, the skill emits a deterministic offline stub derived
    from the trend. This keeps the pipeline runnable and the test suite hermetic
    without weakening the contract.
  - Network I/O is isolated in `runtime/llm_client.py`, outside the skill core
    (`skills/README.md`: isolate side-effects outside the skill)

### Platform Content Constraints (FR-5)

| Platform | `headline_max` | `caption_max` | `hashtag_max` |
|----------|----------------|---------------|---------------|
| YouTube  | 100            | 5000          | 15            |
| Twitter  | 60             | 280           | 3             |
| Instagram| 90             | 2200          | 30            |

---

### Governance & Approval API
- **Function:** `approve_content(draft_id: str = None, draft: dict = None, threshold: float = 0.85) -> ApprovalStatus`
- **Inputs:**
  - `draft_id` (string): identifier of the draft under review
  - `draft` (dict, v1.1): the draft payload. When supplied, its
    `brand_safety_score` is the gate input. When absent, the draft escalates.
  - `threshold` (float): minimum score for auto-approval, default `0.85`
- **Outputs:**
  - `status` (string): one of `['approved', 'rejected', 'needs_review']`
  - `reviewer_comments` (string)
  - `approved` (bool, v1.1): the gate decision
  - `workflow_status` (string, v1.1): `READY_FOR_PUBLISH` | `NEEDS_HUMAN_REVIEW`
  - `reason` (string, v1.1): same justification as `reviewer_comments`
  - `brand_safety_score` (float, v1.1): observed score, `-1.0` if unknown
  - `threshold` (float, v1.1): the applied gate
  - `evaluated_at` (string, v1.1): ISO 8601 evaluation timestamp
- **Gate rule:**
  - `brand_safety_score >= threshold` → `approved=True`, `status='approved'`,
    `workflow_status='READY_FOR_PUBLISH'`
  - `brand_safety_score < threshold` → `approved=False`,
    `status='needs_review'`, `workflow_status='NEEDS_HUMAN_REVIEW'`
  - **Fail-closed:** a missing or unreadable score escalates to human review.
    Absence of evidence is never treated as evidence of safety
    (`specs/_meta.md`: uncertainty must trigger escalation, not execution).
- **Why two status fields (v1.1):** `status` is pinned to the three-value
  governance enum and asserted by `tests/test_skills_interface.py`. The
  publishing pipeline needs the coarser two-state value, so it is exposed as
  `workflow_status` rather than overwriting the canonical field. Both derive
  from a single decision and cannot disagree.
- **Constraints:**
  - Must be triggered by human-in-the-loop or the Safety & Governance Agent
  - At least one of `draft_id` / `draft` is required, else
    `MISSING_DRAFT_REFERENCE` (FR-13: halt rather than assume)

---

### Publishing API
- **Function:** `publish_content(draft_id: str, schedule_time: str) -> PublishResult`
- **Inputs:**
  - `draft_id` (string, required)
  - `schedule_time` (ISO 8601 string, required)
- **Outputs:**
  - `success` (bool)
  - `platform_id` (string)
  - `published_timestamp` (ISO 8601 string)
- **Errors:**
  - `UNAPPROVED_DRAFT`
  - `PLATFORM_ERROR`

---

## Database Schema

### Tables

**Trends**
- `trend_id` (PK)
- `title`
- `platform`
- `score`
- `timestamp`
- `topic` (v1.1)
- `volume` (v1.1)
- `category` (v1.1)
- `context` (v1.2, TEXT)
- `source_url` (v1.2)

**ContentDrafts**
- `draft_id` (PK)
- `trend_id` (FK → Trends)
- `content_text`
- `media_links`
- `platform_format_valid`
- `created_at`
- `headline` (v1.1)
- `caption` (v1.1)
- `brand_safety_score` (v1.1)
- `suggested_hashtags` (v1.1, JSON)
- `generation_mode` (v1.1)
- `generated_by` (v1.1)
- `grounded_on_source` (v1.2)

**ApprovalLogs**
- `approval_id` (PK)
- `draft_id` (FK → ContentDrafts)
- `status`
- `reviewer_comments`
- `approved_at`
- `workflow_status` (v1.1)
- `brand_safety_score` (v1.1)
- `threshold` (v1.1)

**PublishingLogs**
- `publish_id` (PK)
- `draft_id` (FK → ContentDrafts)
- `platform_id`
- `scheduled_time`
- `published_timestamp`

---

### Relationships
- `Trends` 1 → many `ContentDrafts`
- `ContentDrafts` 1 → many `ApprovalLogs`
- `ContentDrafts` 1 → many `PublishingLogs`

---

### Optional ERD (Mermaid.js)
```mermaid
erDiagram
    Trends ||--o{ ContentDrafts : contains
    ContentDrafts ||--o{ ApprovalLogs : reviewed_by
    ContentDrafts ||--o{ PublishingLogs : published_by
