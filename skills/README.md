# Project Chimera — Skills Directory

## Purpose
Skills are deterministic, stateless capabilities that Chimera executes at runtime.

---

## Skill Guidelines
- Each skill must have a defined **input/output contract**.
- Skills are **idempotent** whenever possible.
- Skills do **not bypass human-in-the-loop** for high-risk tasks.
- All executions are logged via MCP.

---

## Critical Skills

### 1. skill_fetch_trends
- **Purpose:** Discover trending topics from supported platforms.
- **Inputs:**
  - platform: str (YouTube / Twitter / Instagram)
  - limit: int (max 50)
- **Outputs:** List of Trend objects
  - trend_id: str
  - title: str
  - timestamp: ISO 8601
  - score: float (0.0–1.0)
- **Deterministic:** Yes
- **MCP Logging:** inputs, outputs, execution time

### 2. skill_generate_content
- **Purpose:** Generate platform-specific content drafts.
- **Inputs:**
  - trend_id: str
  - platform: str
- **Outputs:** ContentDraft object
  - draft_id: str
  - trend_id: str
  - content_text: str
  - media_links: list[str]
  - platform_format_valid: bool
- **Deterministic:** Yes, for same input trend
- **MCP Logging:** inputs, outputs, skill execution

### 3. skill_approve_content
- **Purpose:** Human-in-the-loop content approval.
- **Inputs:**
  - draft_id: str
- **Outputs:** ApprovalStatus object
  - status: str ('approved', 'rejected', 'needs_review')
  - reviewer_comments: str
- **Deterministic:** Partially; depends on human reviewer
- **MCP Logging:** inputs, outputs, approval timestamps

### (Optional future skill)
- skill_publish_content → Publishes approved drafts according to schedule
- skill_analyze_engagement → Optional analytics skill for future scaling
