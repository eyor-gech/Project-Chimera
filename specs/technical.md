# Project Chimera — Technical Specification

## API Contracts

### Trend Discovery API
- **Function:** `fetch_trends(platform: str, limit: int) -> List[Trend]`
- **Inputs:**
  - `platform` (string, required): one of `['YouTube', 'Twitter', 'Instagram']`
  - `limit` (integer, optional): maximum 50
- **Outputs:**
  - List of `Trend` objects:
    - `trend_id` (string)
    - `title` (string)
    - `timestamp` (ISO 8601 string)
    - `score` (float, 0.0–1.0)
- **Errors:**
  - `INVALID_PLATFORM`
  - `NETWORK_ERROR`

---

### Content Generation API
- **Function:** `generate_content(trend_id: str, platform: str) -> ContentDraft`
- **Inputs:**
  - `trend_id` (string, required)
  - `platform` (string, required)
- **Outputs:**
  - `ContentDraft` object:
    - `draft_id` (string)
    - `trend_id` (string)
    - `content_text` (string)
    - `media_links` (list[string])
    - `platform_format_valid` (bool)
- **Validation:**
  - Draft must adhere to platform-specific constraints
  - Content must be original; cannot reuse other agents’ drafts

---

### Governance & Approval API
- **Function:** `approve_content(draft_id: str) -> ApprovalStatus`
- **Inputs:**
  - `draft_id` (string, required)
- **Outputs:**
  - `status` (string): one of `['approved', 'rejected', 'needs_review']`
  - `reviewer_comments` (string)
- **Constraints:**
  - Must be triggered by human-in-the-loop or the Safety & Governance Agent

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

**ContentDrafts**
- `draft_id` (PK)
- `trend_id` (FK → Trends)
- `content_text`
- `media_links`
- `platform_format_valid`
- `created_at`

**ApprovalLogs**
- `approval_id` (PK)
- `draft_id` (FK → ContentDrafts)
- `status`
- `reviewer_comments`
- `approved_at`

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
