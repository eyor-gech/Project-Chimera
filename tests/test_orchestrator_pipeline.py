"""End-to-end tests for the orchestrator, the LLM gateway and the demo.

Spec references: ``specs/orchestration.md`` (deterministic governed flow,
halt on failure), ``specs/functional.md`` (FR-13, FR-14, FR-15).
"""

from __future__ import annotations

import pytest

from runtime import orchestrator
from runtime.llm_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL_CHAIN,
    LLMUnavailable,
    OpenRouterClient,
    get_client,
)
from runtime.orchestrator import STAGES, run_chimera
from skills.skill_approve_content import READY_FOR_PUBLISH


# ==========================================================================
# Orchestrator
# ==========================================================================

class TestRunChimera:
    """specs/orchestration.md: fetch -> generate -> approve -> stop."""

    @pytest.mark.parametrize("platform", ["YouTube", "Twitter", "Instagram"])
    def test_produces_all_pipeline_outputs(self, platform):
        result = run_chimera(platform=platform, limit=2)
        assert len(result["trends"]) == 2
        assert len(result["drafts"]) == 2
        assert len(result["approvals"]) == 2

    def test_drafts_are_linked_to_their_trends(self):
        result = run_chimera(platform="YouTube", limit=3)
        trend_ids = {t["trend_id"] for t in result["trends"]}
        assert {d["trend_id"] for d in result["drafts"]} == trend_ids

    def test_every_draft_is_governed_exactly_once(self):
        result = run_chimera(platform="YouTube", limit=3)
        assert [a["draft_id"] for a in result["approvals"]] == [d["draft_id"] for d in result["drafts"]]

    def test_approvals_are_consistent_with_scores(self):
        for approval in run_chimera(platform="YouTube", limit=3)["approvals"]:
            expected = approval["brand_safety_score"] >= approval["threshold"]
            assert approval["approved"] is expected
            assert approval["workflow_status"] == (
                READY_FOR_PUBLISH if expected else "NEEDS_HUMAN_REVIEW"
            )

    def test_summary_counts_match_the_outputs(self):
        result = run_chimera(platform="Twitter", limit=3)
        summary = result["summary"]
        assert summary["trends"] == len(result["trends"])
        assert summary["drafts"] == len(result["drafts"])
        assert summary["approved"] + summary["escalated"] == summary["drafts"]

    def test_run_stops_after_the_approval_stage(self):
        """No publishing in this stage - a non-goal of the pipeline."""
        assert run_chimera(platform="YouTube", limit=1)["summary"]["next_stage"] == (
            "stopped_after_approval"
        )

    def test_is_deterministic_for_the_same_inputs(self):
        """specs/orchestration.md: orchestration must be deterministic."""
        first = run_chimera(platform="YouTube", limit=2)
        second = run_chimera(platform="YouTube", limit=2)
        assert first["trends"] == second["trends"]
        assert [d["draft_id"] for d in first["drafts"]] == [d["draft_id"] for d in second["drafts"]]

    def test_logger_receives_every_telemetry_event(self):
        events = []
        result = run_chimera(platform="YouTube", limit=1, logger=events.append)
        assert len(events) == len(result["telemetry"])

    def test_telemetry_records_agents_and_spec_refs(self):
        """FR-14: actions are traceable to an agent role and a spec clause."""
        entries = run_chimera(platform="YouTube", limit=1)["telemetry"]
        assert {e["stage"] for e in entries}.issubset(set(STAGES))
        for entry in entries:
            assert entry["agent"]
            assert entry["timestamp"]
            if entry["event"] in {"skill.completed", "run.halted", "run.completed", "run.started"}:
                assert entry.get("spec_refs")

    def test_telemetry_covers_all_three_stages(self):
        stages = {e["stage"] for e in run_chimera(platform="YouTube", limit=1)["telemetry"]}
        assert stages == set(STAGES)

    def test_run_is_announced_and_completed(self):
        events = [e["event"] for e in run_chimera(platform="YouTube", limit=1)["telemetry"]]
        assert events[0] == "run.started"
        assert events[-1] == "run.completed"

    def test_telemetry_does_not_leak_between_runs(self):
        run_chimera(platform="YouTube", limit=1)
        run_chimera(platform="YouTube", limit=1)
        assert len(orchestrator.TELEMETRY) == len(run_chimera(platform="YouTube", limit=1)["telemetry"])

    def test_invalid_platform_halts_and_logs(self):
        """FR-15: halt on error instead of returning partial results."""
        with pytest.raises(Exception) as excinfo:
            run_chimera(platform="TikTok", limit=1)
        assert getattr(excinfo.value, "code", None) == "INVALID_PLATFORM"
        assert orchestrator.TELEMETRY[-1]["event"] == "run.halted"

    def test_halt_event_carries_the_spec_error_code(self):
        with pytest.raises(Exception):
            run_chimera(platform="YouTube", limit=999)
        assert orchestrator.TELEMETRY[-1]["error"] == "INVALID_LIMIT"

    def test_custom_safety_threshold_flows_to_the_gate(self):
        result = run_chimera(platform="YouTube", limit=3, safety_threshold=0.0)
        assert all(a["approved"] for a in result["approvals"])


# ==========================================================================
# LLM gateway (runtime/llm_client.py)
# ==========================================================================

class TestOpenRouterClient:
    """The network side effect is isolated here, per skills/README.md."""

    def test_defaults_match_the_brief(self):
        client = OpenRouterClient()
        assert client.base_url == DEFAULT_BASE_URL == "https://openrouter.ai/api/v1"
        assert client.model_chain == DEFAULT_MODEL_CHAIN
        assert client.model_chain[0] == "google/gemma-4-26b-a4b-it:free"
        assert client.model_chain[-1] == "openai/gpt-4o-mini"

    def test_chain_leads_with_free_tier_models(self):
        """Free-first chain; the paid model is only a last-resort safety net."""
        assert all(":free" in model for model in DEFAULT_MODEL_CHAIN[:-1])
        assert len(DEFAULT_MODEL_CHAIN) > 1

    def test_retired_claude_model_is_not_in_the_chain(self):
        """anthropic/claude-3.5-sonnet returns HTTP 404 upstream."""
        assert "anthropic/claude-3.5-sonnet" not in DEFAULT_MODEL_CHAIN

    @pytest.mark.parametrize("raw,expected", [
        ('{"a": 1}', {"a": 1}),                                  # bare JSON
        ('```json\n{"a": 1}\n```', {"a": 1}),                    # fenced JSON
        ('```\n{"a": 1}\n```', {"a": 1}),                        # unlabelled fence
        ('Here you go:\n{"a": 1}\nHope that helps!', {"a": 1}), # prose around it
        ('  {"a": 1}  ', {"a": 1}),                              # padded
    ])
    def test_json_parser_tolerates_fences_and_prose(self, raw, expected):
        from runtime.llm_client import _parse_json_object

        assert _parse_json_object(raw) == expected

    @pytest.mark.parametrize("raw", ["", "not json at all", "[1, 2, 3]", '"a string"'])
    def test_json_parser_rejects_non_objects(self, raw):
        from runtime.llm_client import _parse_json_object

        with pytest.raises(ValueError):
            _parse_json_object(raw)

    def test_api_key_is_read_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
        assert OpenRouterClient().api_key == "sk-test-123"

    def test_unavailable_without_a_key(self, offline_llm):
        assert OpenRouterClient().is_available is False

    def test_offline_flag_forces_unavailable(self, monkeypatch):
        monkeypatch.delenv("CHIMERA_OFFLINE", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
        assert OpenRouterClient().is_available is True

        monkeypatch.setenv("CHIMERA_OFFLINE", "1")
        assert OpenRouterClient().is_available is False

    def test_model_chain_is_overridable(self, monkeypatch):
        monkeypatch.setenv("CHIMERA_MODEL_CHAIN", "vendor/model-a, vendor/model-b")
        assert OpenRouterClient().model_chain == ("vendor/model-a", "vendor/model-b")

    def test_base_url_is_overridable(self, monkeypatch):
        monkeypatch.setenv("CHIMERA_OPENROUTER_BASE_URL", "https://proxy.internal/v1")
        assert OpenRouterClient().base_url == "https://proxy.internal/v1"

    def test_complete_json_raises_when_unavailable(self, offline_llm):
        with pytest.raises(LLMUnavailable):
            OpenRouterClient().complete_json("system", "user")

    def test_complete_json_returns_payload_and_model(self, monkeypatch):
        """A single successful response is returned with the model that served it."""
        monkeypatch.delenv("CHIMERA_OFFLINE", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")

        class _Message:
            content = '{"headline": "H", "caption": "C", "brand_safety_score": 0.9}'

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        calls = []

        class _Completions:
            def create(self, **kwargs):
                calls.append(kwargs["model"])
                if len(calls) == 1:
                    raise RuntimeError("primary model retired")
                return _Response()

        class _Chat:
            completions = _Completions()

        class _FakeClient:
            def __init__(self, **_kwargs):
                self.chat = _Chat()

        monkeypatch.setitem(__import__("sys").modules, "openai", type("_M", (), {"OpenAI": _FakeClient}))

        payload, model = OpenRouterClient().complete_json("system", "user")
        assert payload["headline"] == "H"
        # The chain is walked in order, so the primary is tried first and the
        # failing entry hands off to the next model.
        assert calls[0] == DEFAULT_MODEL_CHAIN[0]
        assert model == DEFAULT_MODEL_CHAIN[1]

    def test_fenced_json_response_is_accepted(self, monkeypatch):
        """Providers may wrap JSON in a fence despite response_format."""
        monkeypatch.delenv("CHIMERA_OFFLINE", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
        monkeypatch.setenv("CHIMERA_MODEL_CHAIN", "vendor/fenced")

        class _Message:
            content = '```json\n{"headline": "H", "brand_safety_score": 0.9}\n```'

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        class _Completions:
            def create(self, **_kwargs):
                return _Response()

        class _Chat:
            completions = _Completions()

        class _FakeClient:
            def __init__(self, **_kwargs):
                self.chat = _Chat()

        monkeypatch.setitem(__import__("sys").modules, "openai", type("_M", (), {"OpenAI": _FakeClient}))

        payload, model = OpenRouterClient().complete_json("system", "user")
        assert payload["headline"] == "H"
        assert model == "vendor/fenced"

    def test_get_client_returns_a_fresh_instance(self):
        assert get_client() is not get_client()

    def test_rate_limit_detection(self):
        """429 detection drives retry-vs-skip; it must be status-code based."""
        from runtime.llm_client import _is_rate_limited

        class _RateLimited(Exception):
            status_code = 429

        assert _is_rate_limited(_RateLimited("boom")) is True
        assert _is_rate_limited(Exception("Error code: 429 - rate limited")) is True
        assert _is_rate_limited(Exception("Error code: 404 - not found")) is False
        assert _is_rate_limited(ValueError("bad json")) is False

    def test_rate_limited_model_is_retried_before_falling_through(self, monkeypatch):
        """A transient 429 must not skip straight past the primary model."""
        monkeypatch.delenv("CHIMERA_OFFLINE", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
        monkeypatch.setenv("CHIMERA_MODEL_CHAIN", "vendor/primary,vendor/backup")
        monkeypatch.setattr("runtime.llm_client.time.sleep", lambda _s: None)

        attempts = []

        class _RateLimited(Exception):
            status_code = 429

        class _Message:
            content = '{"headline": "H", "brand_safety_score": 0.9}'

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        class _Completions:
            def create(self, **kwargs):
                model = kwargs["model"]
                attempts.append(model)
                if model == "vendor/primary" and attempts.count("vendor/primary") <= 2:
                    raise _RateLimited("temporarily rate-limited upstream")
                return _Response()

        class _Chat:
            completions = _Completions()

        class _FakeClient:
            def __init__(self, **_kwargs):
                self.chat = _Chat()

        monkeypatch.setitem(__import__("sys").modules, "openai", type("_M", (), {"OpenAI": _FakeClient}))

        payload, model = OpenRouterClient(max_rate_limit_retries=2).complete_json("s", "u")
        # Two retries on the primary (3 attempts total), then it succeeds.
        assert attempts == ["vendor/primary"] * 3
        assert model == "vendor/primary"
        assert payload["headline"] == "H"

    def test_persistent_rate_limit_falls_through_to_the_next_model(self, monkeypatch):
        monkeypatch.delenv("CHIMERA_OFFLINE", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
        monkeypatch.setenv("CHIMERA_MODEL_CHAIN", "vendor/primary,vendor/backup")
        monkeypatch.setattr("runtime.llm_client.time.sleep", lambda _s: None)

        seen = []

        class _RateLimited(Exception):
            status_code = 429

        class _Message:
            content = '{"headline": "H", "brand_safety_score": 0.9}'

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        class _Completions:
            def create(self, **kwargs):
                model = kwargs["model"]
                seen.append(model)
                if model == "vendor/primary":
                    raise _RateLimited("hard limited")
                return _Response()

        class _Chat:
            completions = _Completions()

        class _FakeClient:
            def __init__(self, **_kwargs):
                self.chat = _Chat()

        monkeypatch.setitem(__import__("sys").modules, "openai", type("_M", (), {"OpenAI": _FakeClient}))

        _, model = OpenRouterClient(max_rate_limit_retries=1).complete_json("s", "u")
        assert model == "vendor/backup"
        assert seen == ["vendor/primary", "vendor/primary", "vendor/backup"]

    def test_retry_settings_are_configurable(self, monkeypatch):
        monkeypatch.setenv("CHIMERA_LLM_RETRIES", "4")
        monkeypatch.setenv("CHIMERA_LLM_RETRY_DELAY", "0.25")
        client = OpenRouterClient()
        assert client.max_rate_limit_retries == 4
        assert client.retry_base_delay == 0.25

    def test_all_models_rate_limited_raises_unavailable(self, monkeypatch):
        monkeypatch.delenv("CHIMERA_OFFLINE", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
        monkeypatch.setenv("CHIMERA_MODEL_CHAIN", "vendor/a,vendor/b")
        monkeypatch.setattr("runtime.llm_client.time.sleep", lambda _s: None)

        class _RateLimited(Exception):
            status_code = 429

        class _Completions:
            def create(self, **_kwargs):
                raise _RateLimited("limited")

        class _Chat:
            completions = _Completions()

        class _FakeClient:
            def __init__(self, **_kwargs):
                self.chat = _Chat()

        monkeypatch.setitem(__import__("sys").modules, "openai", type("_M", (), {"OpenAI": _FakeClient}))

        with pytest.raises(LLMUnavailable) as excinfo:
            OpenRouterClient(max_rate_limit_retries=0).complete_json("s", "u")
        # Both models are reported so the failure is diagnosable (FR-14).
        assert "vendor/a" in str(excinfo.value) and "vendor/b" in str(excinfo.value)


class TestGenerationFallback:
    """The pipeline must survive a provider failure (FR-15)."""

    def test_llm_error_falls_back_to_offline_stub(self, monkeypatch):
        monkeypatch.delenv("CHIMERA_OFFLINE", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")

        def _boom(*_args, **_kwargs):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr("runtime.llm_client.OpenRouterClient.complete_json", _boom)

        from skills.skill_generate_content import generate_content

        draft = generate_content(trend_id="t-1", topic="Resilience", platform="YouTube")
        assert draft["generation_mode"] == "offline-stub"
        assert draft["generated_by"] == "offline-deterministic-stub"
        assert draft["headline"]

    def test_malformed_model_output_falls_back(self, monkeypatch):
        monkeypatch.delenv("CHIMERA_OFFLINE", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
        monkeypatch.setattr(
            "runtime.llm_client.OpenRouterClient.complete_json",
            lambda self, **_: ({"headline": "", "brand_safety_score": "n/a"}, "vendor/bad-model"),
        )

        from skills.skill_generate_content import generate_content

        draft = generate_content(trend_id="t-1", topic="Resilience", platform="YouTube")
        assert draft["generation_mode"] == "offline-stub"
        assert 0.0 <= draft["brand_safety_score"] <= 1.0


# ==========================================================================
# Demo entry point
# ==========================================================================

class TestDemo:
    """demo.py is the interview surface, so it is smoke-tested too."""

    def test_runs_offline_and_exits_clean(self, capsys):
        import demo

        assert demo.main(["YouTube", "2", "--offline", "--no-color"]) == 0

        out = capsys.readouterr().out
        assert "PROJECT CHIMERA" in out
        assert "Trend Discovery" in out
        assert "Governance Approval" in out
        assert "No content was published" in out

    def test_no_network_access_when_offline_flag_is_used(self, capsys):
        import demo

        demo.main(["Twitter", "1", "--offline", "--no-color"])
        assert "offline deterministic stub" in capsys.readouterr().out

    def test_rejects_platform_outside_the_spec_allowlist(self):
        """specs/technical.md approves only three platforms; argparse blocks others."""
        import demo

        with pytest.raises(SystemExit) as excinfo:
            demo.main(["TikTok", "--offline", "--no-color"])
        assert excinfo.value.code == 2

    def test_pipeline_halt_exits_nonzero_and_publishes_nothing(self, capsys, monkeypatch):
        """FR-15: a mid-run failure halts visibly instead of half-running."""
        import demo
        from skills.skill_fetch_trends import TrendDiscoveryError

        def _halt(*_args, **_kwargs):
            raise TrendDiscoveryError("NETWORK_ERROR", "trend provider unreachable")

        monkeypatch.setattr("demo.run_chimera", _halt)
        assert demo.main(["YouTube", "2", "--offline", "--no-color"]) == 1

        out = capsys.readouterr().out
        assert "PIPELINE HALTED" in out
        assert "NETWORK_ERROR" in out

    def test_style_can_be_disabled(self):
        from demo import Style

        original = Style.enabled
        try:
            Style.disable()
            assert Style.paint("plain", "red") == "plain"
        finally:
            Style.enabled = original

    def test_style_emits_ansi_when_enabled(self):
        from demo import Style

        original = Style.enabled
        try:
            Style.enabled = True
            assert Style.paint("x", "red", "bold").startswith("\033[")
        finally:
            Style.enabled = original
