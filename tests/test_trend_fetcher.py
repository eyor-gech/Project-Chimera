# --- TDD -------------------------------------------------------------------
# tests/test_trend_fetcher.py
#
# Original baseline contract, authored in the failing-test phase (Task 3.1)
# straight from specs/technical.md -> "Trend Discovery API". Left unchanged on
# purpose: it is the historical TDD baseline the implementation was written
# against.
#
# Broader coverage (additive fields, error codes, determinism, generation and
# governance) now lives in:
#   tests/test_skill_contracts.py
#   tests/test_orchestrator_pipeline.py
#
# The unused `import pytest` below is intentional: removing it would rewrite the
# baseline file this record refers to.
import pytest  # noqa: F401  (kept for the baseline record above)

from skills.skill_fetch_trends import fetch_trends


def test_fetch_trends_structure():
    trends = fetch_trends(platform="YouTube", limit=5)
    # Assertion for correct structure
    for trend in trends:
        assert "trend_id" in trend
        assert "title" in trend
        assert "timestamp" in trend
        assert "score" in trend
