"""Contract tests for the three Chimera skills.

Every test maps to a specification clause so a failure is traceable:

* ``specs/technical.md`` -> Trend Discovery / Content Generation / Governance APIs
* ``specs/functional.md`` -> FR-1, FR-2, FR-4, FR-5, FR-6, FR-7, FR-8, FR-13
* ``specs/_meta.md``      -> determinism, halt-on-ambiguity
"""

from __future__ import annotations

from datetime import datetime

import pytest

from skills.skill_approve_content import (
    DEFAULT_SAFETY_THRESHOLD,
    NEEDS_HUMAN_REVIEW,
    READY_FOR_PUBLISH,
    REASON_FLAGGED,
    REASON_NO_EVIDENCE,
    REASON_PASSED,
    UNKNOWN_SCORE,
    ApprovalError,
    approve_content,
)
from skills.skill_fetch_trends import (
    MAX_LIMIT,
    SUPPORTED_PLATFORMS,
    TrendDiscoveryError,
    fetch_trends,
    resolve_trend,
)
from skills.skill_generate_content import (
    PLATFORM_CONSTRAINTS,
    ContentGenerationError,
    GeneratedDraft,
    check_platform_format,
    generate_content,
)

SPEC_TREND_KEYS = {"trend_id", "title", "timestamp", "score"}
DEMO_TREND_KEYS = {"trend_id", "topic", "volume", "category"}
SPEC_DRAFT_KEYS = {"draft_id", "trend_id", "content_text", "media_links", "platform_format_valid"}
DEMO_DRAFT_KEYS = {"headline", "caption", "brand_safety_score", "suggested_hashtags"}


# ==========================================================================
# Skill 1 - fetch_trends
# ==========================================================================

class TestFetchTrends:
    """FR-1, FR-2: discover, normalise and score trends."""

    def test_returns_requested_number_of_trends(self):
        assert len(fetch_trends(platform="YouTube", limit=5)) == 5

    def test_default_limit_is_three(self):
        assert len(fetch_trends(platform="YouTube")) == 3

    @pytest.mark.parametrize("platform", SUPPORTED_PLATFORMS)
    def test_contains_spec_and_demo_fields(self, platform):
        for trend in fetch_trends(platform=platform, limit=4):
            assert SPEC_TREND_KEYS.issubset(trend), "specs/technical.md fields missing"
            assert DEMO_TREND_KEYS.issubset(trend), "demo fields missing"

    @pytest.mark.parametrize("platform", SUPPORTED_PLATFORMS)
    def test_score_is_normalized_and_ranked_descending(self, platform):
        scores = [t["score"] for t in fetch_trends(platform=platform, limit=6)]
        assert all(0.0 <= score <= 1.0 for score in scores)
        assert scores == sorted(scores, reverse=True)

    def test_timestamp_is_iso_8601(self):
        trend = fetch_trends(platform="YouTube", limit=1)[0]
        assert datetime.fromisoformat(trend["timestamp"])

    def test_volume_and_category_are_populated(self):
        for trend in fetch_trends(platform="Twitter", limit=5):
            assert isinstance(trend["volume"], int) and trend["volume"] > 0
            assert isinstance(trend["category"], str) and trend["category"]

    def test_is_deterministic_across_calls(self):
        """specs/_meta.md: skills must be deterministic."""
        assert fetch_trends(platform="YouTube", limit=5) == fetch_trends(platform="YouTube", limit=5)

    def test_trend_ids_are_unique_within_a_run(self):
        ids = [t["trend_id"] for t in fetch_trends(platform="Instagram", limit=8)]
        assert len(set(ids)) == len(ids)

    def test_title_mirrors_topic(self):
        trend = fetch_trends(platform="YouTube", limit=1)[0]
        assert trend["title"] == trend["topic"]

    def test_zero_limit_returns_empty_list(self):
        assert fetch_trends(platform="YouTube", limit=0) == []

    def test_limit_above_catalogue_size_is_capped_not_an_error(self):
        assert len(fetch_trends(platform="YouTube", limit=MAX_LIMIT)) == 8

    @pytest.mark.parametrize("platform", ["TikTok", "", "youtube", None, 42])
    def test_invalid_platform_halts_with_spec_error_code(self, platform):
        """FR-13: halt on invalid input instead of assuming (INVALID_PLATFORM)."""
        with pytest.raises(TrendDiscoveryError) as excinfo:
            fetch_trends(platform=platform, limit=3)
        assert excinfo.value.code == "INVALID_PLATFORM"

    @pytest.mark.parametrize("limit", [-1, MAX_LIMIT + 1, "3", 1.5, True])
    def test_invalid_limit_halts_with_spec_error_code(self, limit):
        with pytest.raises(TrendDiscoveryError) as excinfo:
            fetch_trends(platform="YouTube", limit=limit)
        assert excinfo.value.code == "INVALID_LIMIT"


class TestResolveTrend:
    """Topic lookup shared with skill_generate_content."""

    def test_resolves_known_trend(self):
        trend = fetch_trends(platform="YouTube", limit=1)[0]
        assert resolve_trend("YouTube", trend["trend_id"])["topic"] == trend["topic"]

    def test_unknown_trend_returns_none(self):
        assert resolve_trend("YouTube", "does-not-exist") is None

    def test_invalid_platform_halts(self):
        with pytest.raises(TrendDiscoveryError):
            resolve_trend("MySpace", "whatever")


# ==========================================================================
# Skill 2 - generate_content
# ==========================================================================

class TestGenerateContent:
    """FR-4, FR-5, FR-6: typed, platform-adapted, traceable drafts."""

    def test_contains_spec_and_demo_fields(self):
        trend = fetch_trends(platform="YouTube", limit=1)[0]
        draft = generate_content(trend_id=trend["trend_id"], topic=trend["topic"],
                                  platform="YouTube")
        assert SPEC_DRAFT_KEYS.issubset(draft), "specs/technical.md fields missing"
        assert DEMO_DRAFT_KEYS.issubset(draft), "demo fields missing"

    def test_spec_signature_without_topic_still_works(self):
        """specs/technical.md declares generate_content(trend_id, platform)."""
        draft = generate_content(trend_id="123", platform="YouTube")
        assert draft["platform_format_valid"] is True
        assert draft["trend_id"] == "123"

    def test_resolves_topic_from_trend_id_when_omitted(self):
        trend = fetch_trends(platform="Instagram", limit=1)[0]
        draft = generate_content(trend_id=trend["trend_id"], platform="Instagram")
        assert draft["topic"] == trend["topic"]

    def test_draft_is_traceable_to_its_trend(self):
        """FR-6: drafts must trace back to the originating trend."""
        trend = fetch_trends(platform="YouTube", limit=1)[0]
        draft = generate_content(trend_id=trend["trend_id"], topic=trend["topic"],
                                 platform="YouTube")
        assert draft["trend_id"] == trend["trend_id"]
        assert draft["trend_id"] in draft["draft_id"] or draft["draft_id"]

    @pytest.mark.parametrize("platform", SUPPORTED_PLATFORMS)
    def test_brand_safety_score_within_unit_interval(self, platform):
        for topic in ("MCP Server Ecosystem", "Creator Burnout Talk", "Governance Guardrails"):
            draft = generate_content(trend_id="t-1", topic=topic, platform=platform)
            assert 0.0 <= draft["brand_safety_score"] <= 1.0

    @pytest.mark.parametrize("platform", SUPPORTED_PLATFORMS)
    def test_respects_platform_length_constraints(self, platform):
        """FR-5: content is adapted to platform format and length limits."""
        limits = PLATFORM_CONSTRAINTS[platform]
        draft = generate_content(
            trend_id="t-1",
            topic="A Very Long Trending Topic Name That Exceeds Headline Limits " * 5,
            platform=platform,
        )
        assert len(draft["headline"]) <= limits["headline_max"]
        assert len(draft["caption"]) <= limits["caption_max"]
        assert len(draft["suggested_hashtags"]) <= limits["hashtag_max"]

    @pytest.mark.parametrize("platform", SUPPORTED_PLATFORMS)
    def test_hashtags_are_prefixed_and_unique(self, platform):
        draft = generate_content(trend_id="t-1", topic="OpenClaw Integration",
                                 platform=platform)
        tags = draft["suggested_hashtags"]
        assert tags, "at least one hashtag expected"
        assert all(tag.startswith("#") and len(tag) > 1 for tag in tags)
        assert len(set(tags)) == len(tags)

    def test_content_text_embeds_headline_and_caption(self):
        draft = generate_content(trend_id="t-1", topic="Agent Swarms", platform="YouTube")
        assert draft["headline"] in draft["content_text"]
        assert draft["caption"] in draft["content_text"]

    def test_media_links_is_a_list(self):
        draft = generate_content(trend_id="t-1", topic="Vector Search", platform="YouTube")
        assert isinstance(draft["media_links"], list)

    def test_draft_id_is_deterministic(self):
        """Idempotency guideline in skills/README.md."""
        first = generate_content(trend_id="t-1", topic="Edge Inference", platform="YouTube")
        second = generate_content(trend_id="t-1", topic="Edge Inference", platform="YouTube")
        assert first["draft_id"] == second["draft_id"]

    def test_draft_id_differs_per_platform(self):
        a = generate_content(trend_id="t-1", topic="Edge Inference", platform="YouTube")
        b = generate_content(trend_id="t-1", topic="Edge Inference", platform="Twitter")
        assert a["draft_id"] != b["draft_id"]

    def test_uses_offline_stub_when_no_api_key(self, offline_llm):
        draft = generate_content(trend_id="t-1", topic="Fallback Check", platform="YouTube")
        assert draft["generation_mode"] == "offline-stub"

    def test_live_llm_payload_is_parsed_and_validated(self, monkeypatch):
        """A provider response is mapped onto the full draft contract."""
        monkeypatch.delenv("CHIMERA_OFFLINE", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        def fake_request(topic, platform, context=None):
            return {
                "headline": "Live headline",
                "caption": "Live caption",
                "brand_safety_score": 0.93,
                "suggested_hashtags": ["#Live", "#Chimera"],
                "_model": "anthropic/claude-3.5-sonnet",
            }

        monkeypatch.setattr("skills.skill_generate_content._request_llm_draft", fake_request)
        draft = generate_content(trend_id="t-1", topic="Live Topic", platform="YouTube")

        assert draft["generation_mode"] == "live-llm"
        assert draft["generated_by"] == "anthropic/claude-3.5-sonnet"
        assert draft["headline"] == "Live headline"
        assert draft["brand_safety_score"] == 0.93
        assert draft["suggested_hashtags"] == ["#Live", "#Chimera"]
        assert draft["platform_format_valid"] is True

    @pytest.mark.parametrize("platform", ["TikTok", "", None])
    def test_invalid_platform_halts(self, platform):
        with pytest.raises(ContentGenerationError) as excinfo:
            generate_content(trend_id="t-1", topic="x", platform=platform)
        assert excinfo.value.code == "INVALID_PLATFORM"

    def test_empty_trend_id_halts(self):
        with pytest.raises(ContentGenerationError) as excinfo:
            generate_content(trend_id="", topic="x", platform="YouTube")
        assert excinfo.value.code == "INVALID_TREND_ID"


class TestSourceGrounding:
    """FR-16 (v1.2): drafts analyse the trend's content/comments, not the title."""

    def _capture_llm(self, monkeypatch):
        captured = {}

        def fake_request(topic, platform, context=None):
            captured["topic"] = topic
            captured["context"] = context
            return {
                "headline": "Grounded headline",
                "caption": "Grounded caption",
                "brand_safety_score": 0.91,
                "suggested_hashtags": ["#Grounded"],
                "_model": "llama3.1",
            }

        monkeypatch.setattr("skills.skill_generate_content._request_llm_draft", fake_request)
        return captured

    def test_context_is_forwarded_to_the_llm(self, monkeypatch):
        captured = self._capture_llm(monkeypatch)
        source = "Source content:\nAn article about vector databases.\n\nTop comments:\n- It is fast."

        draft = generate_content(
            trend_id="t-1", topic="Vector Search", platform="YouTube", context=source
        )

        assert captured["context"] == source
        assert draft["grounded_on_source"] is True
        assert draft["generation_mode"] == "live-llm"

    def test_no_context_means_not_grounded(self, monkeypatch):
        captured = self._capture_llm(monkeypatch)
        draft = generate_content(trend_id="t-1", topic="Vector Search", platform="YouTube")
        assert captured["context"] is None
        assert draft["grounded_on_source"] is False

    def test_offline_stub_is_never_marked_grounded(self, offline_llm):
        """The stub ignores source material, so it must not claim to be grounded."""
        draft = generate_content(
            trend_id="t-1", topic="Vector Search", platform="YouTube", context="Some material"
        )
        assert draft["generation_mode"] == "offline-stub"
        assert draft["grounded_on_source"] is False

    def test_context_appended_to_user_prompt(self, monkeypatch):
        """The source block must reach the model, not just the function call."""
        from skills.skill_generate_content import _SOURCE_CONTEXT_TEMPLATE, _USER_PROMPT_TEMPLATE

        base = _USER_PROMPT_TEMPLATE.format(
            platform="YouTube", topic="T", headline_max=100,
            caption_max=5000, hashtag_max=15,
        )
        prompt = base + _SOURCE_CONTEXT_TEMPLATE.format(context="MATERIAL")
        assert prompt.startswith(base)
        assert "MATERIAL" in prompt

    def test_orchestrator_forwards_trend_context(self, monkeypatch):
        """Stage 2 must pass the trend's analysed context into the skill."""
        import skills.skill_generate_content as sgc

        seen = {}
        original = sgc.generate_content

        def spy(*args, **kwargs):
            seen["context"] = kwargs.get("context")
            return original(*args, **kwargs)

        monkeypatch.setattr("runtime.orchestrator.generate_content", spy)
        monkeypatch.setattr(
            sgc, "_request_llm_draft",
            lambda topic, platform, context=None: {
                "headline": "H", "caption": "C", "brand_safety_score": 0.9,
                "suggested_hashtags": ["#A"], "_model": "llama3.1",
            },
        )
        monkeypatch.setattr(
            "skills.skill_fetch_trends.build_source_context",
            lambda item: {"context": "CTX", "source_url": "https://e/x", "comments": 1},
        )

        import skills.skill_fetch_trends as sft

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        def fake_get(url, timeout=None):
            if url.endswith("topstories.json"):
                return FakeResponse([7])
            return FakeResponse({"id": 7, "title": "Story", "url": "https://e/x",
                                "score": 10, "kids": [1]})

        monkeypatch.setattr(sft.requests, "get", fake_get)

        from runtime.orchestrator import run_chimera

        result = run_chimera(platform="Twitter", limit=1, use_real_api=True)
        assert seen["context"] == "CTX"
        assert result["drafts"][0]["grounded_on_source"] is True


class TestRealApiTrends:
    """The live trend path attaches analysed source material (FR-16)."""

    def test_context_and_source_url_are_attached(self, monkeypatch):
        import skills.skill_fetch_trends as sft

        monkeypatch.setattr(
            sft, "build_source_context",
            lambda item: {"context": "CTX", "source_url": "https://e/x", "comments": 3},
        )

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        def fake_get(url, timeout=None):
            if url.endswith("topstories.json"):
                return FakeResponse([7])
            return FakeResponse({"id": 7, "title": "Real Story", "url": "https://e/x",
                                "score": 250, "kids": [1, 2]})

        monkeypatch.setattr(sft.requests, "get", fake_get)

        trend = fetch_trends(platform="Twitter", limit=1, use_real_api=True)[0]
        assert trend["title"] == "Real Story"
        assert trend["context"] == "CTX"
        assert trend["source_url"] == "https://e/x"
        assert trend["volume"] == 250000

    def test_offline_trends_expose_empty_context_fields(self):
        trend = fetch_trends(platform="YouTube", limit=1)[0]
        assert trend["context"] == ""
        assert trend["source_url"] == ""


class TestGeneratedDraftModel:
    """pydantic boundary validation of the LLM response."""

    def test_accepts_well_formed_payload(self):
        model = GeneratedDraft(headline="H", caption="C", brand_safety_score=0.9,
                               suggested_hashtags=["#A"])
        assert model.brand_safety_score == 0.9

    @pytest.mark.parametrize("raw,expected", [
        (92, 0.92),      # percentage style
        ("0.88", 0.88),  # string style
        (1, 1.0),        # boundary
        (0, 0.0),        # boundary
        (150, 1.0),      # clamped
        (-3, 0.0),       # clamped
    ])
    def test_normalizes_and_clamps_scores(self, raw, expected):
        model = GeneratedDraft(headline="H", brand_safety_score=raw)
        assert model.brand_safety_score == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["high", None, [0.5], {}])
    def test_rejects_non_numeric_scores(self, raw):
        with pytest.raises(Exception):
            GeneratedDraft(headline="H", brand_safety_score=raw)

    def test_defaults_missing_optional_fields(self):
        model = GeneratedDraft(headline="H", brand_safety_score=0.8)
        assert model.caption == ""
        assert model.suggested_hashtags == []

    def test_rejects_empty_headline(self):
        with pytest.raises(Exception):
            GeneratedDraft(headline="", brand_safety_score=0.8)


class TestPlatformFormat:
    """FR-5 format check exposed for direct verification."""

    def test_accepts_conforming_draft(self):
        assert check_platform_format("Twitter", "Short headline", "A short caption") is True

    def test_rejects_overlong_caption(self):
        assert check_platform_format("Twitter", "H", "x" * 281) is False

    def test_rejects_empty_caption(self):
        assert check_platform_format("YouTube", "H", "") is False


# ==========================================================================
# Skill 3 - approve_content
# ==========================================================================

class TestApproveContent:
    """FR-7, FR-8, FR-9: classify, then gate publishing."""

    @pytest.mark.parametrize("score", [0.85, 0.9, 0.99, 1.0])
    def test_score_at_or_above_threshold_is_approved(self, score):
        approval = approve_content(draft_id="d-1", draft={"brand_safety_score": score})
        assert approval["approved"] is True
        assert approval["status"] == "approved"
        assert approval["workflow_status"] == READY_FOR_PUBLISH
        assert approval["reason"] == REASON_PASSED

    @pytest.mark.parametrize("score", [0.0, 0.5, 0.84])
    def test_score_below_threshold_escalates(self, score):
        approval = approve_content(draft_id="d-1", draft={"brand_safety_score": score})
        assert approval["approved"] is False
        assert approval["status"] == "needs_review"
        assert approval["workflow_status"] == NEEDS_HUMAN_REVIEW
        assert approval["reason"] == REASON_FLAGGED

    def test_threshold_boundary_is_inclusive(self):
        assert approve_content(draft_id="d", draft={"brand_safety_score": 0.85})["approved"] is True
        assert approve_content(draft_id="d", draft={"brand_safety_score": 0.8499})["approved"] is False

    def test_custom_threshold_is_honoured(self):
        approval = approve_content(draft_id="d", draft={"brand_safety_score": 0.7}, threshold=0.6)
        assert approval["approved"] is True
        assert approval["threshold"] == 0.6

    def test_default_threshold_is_point_eighty_five(self):
        assert DEFAULT_SAFETY_THRESHOLD == 0.85

    def test_spec_signature_with_draft_id_only_escalates(self):
        """No safety evidence -> escalate, never assume safe (specs/_meta.md)."""
        approval = approve_content(draft_id="abc")
        assert approval["approved"] is False
        assert approval["status"] == "needs_review"
        assert approval["reason"] == REASON_NO_EVIDENCE
        assert approval["brand_safety_score"] == UNKNOWN_SCORE

    def test_missing_score_key_escalates(self):
        approval = approve_content(draft_id="d", draft={"headline": "H"})
        assert approval["workflow_status"] == NEEDS_HUMAN_REVIEW

    @pytest.mark.parametrize("bad", ["high", None, [0.9], True, {}])
    def test_unreadable_score_escalates(self, bad):
        approval = approve_content(draft_id="d", draft={"brand_safety_score": bad})
        assert approval["approved"] is False
        assert approval["workflow_status"] == NEEDS_HUMAN_REVIEW

    def test_status_is_always_in_the_canonical_spec_enum(self):
        for score in (0.1, 0.85, 1.0):
            assert approve_content(draft_id="d", draft={"brand_safety_score": score})["status"] in (
                "approved", "rejected", "needs_review"
            )

    def test_reason_and_reviewer_comments_agree(self):
        """Same decision, exposed under both the spec and demo field names."""
        approval = approve_content(draft_id="d", draft={"brand_safety_score": 0.95})
        assert approval["reason"] == approval["reviewer_comments"]

    def test_draft_id_taken_from_draft_when_not_passed(self):
        approval = approve_content(draft={"draft_id": "from-draft", "brand_safety_score": 0.99})
        assert approval["draft_id"] == "from-draft"

    def test_out_of_range_scores_are_clamped_before_gating(self):
        assert approve_content(draft_id="d", draft={"brand_safety_score": 5.0})["approved"] is True
        assert approve_content(draft_id="d", draft={"brand_safety_score": -5.0})["approved"] is False

    def test_evaluation_timestamp_is_iso_8601(self):
        approval = approve_content(draft_id="d", draft={"brand_safety_score": 0.9})
        assert datetime.fromisoformat(approval["evaluated_at"])

    def test_missing_reference_halts(self):
        """FR-13: halt rather than approve an unidentifiable draft."""
        with pytest.raises(ApprovalError) as excinfo:
            approve_content()
        assert excinfo.value.code == "MISSING_DRAFT_REFERENCE"

    def test_non_dict_draft_halts(self):
        with pytest.raises(ApprovalError) as excinfo:
            approve_content(draft_id="d", draft="not-a-dict")
        assert excinfo.value.code == "INVALID_DRAFT"

    def test_pipeline_drafts_are_all_classified(self):
        """Every draft the pipeline produces gets a governance decision."""
        for trend in fetch_trends(platform="YouTube", limit=3):
            draft = generate_content(trend_id=trend["trend_id"], topic=trend["topic"],
                                     platform="YouTube")
            approval = approve_content(draft_id=draft["draft_id"], draft=draft)
            approved = approval["workflow_status"] == READY_FOR_PUBLISH
            assert approved == (approval["brand_safety_score"] >= DEFAULT_SAFETY_THRESHOLD)
