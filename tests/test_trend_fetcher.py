import pytest
from skills.skill_fetch_trends import fetch_trends

def test_fetch_trends_structure():
    trends = fetch_trends(platform="YouTube", limit=5)
    # Assertion for correct structure
    for trend in trends:
        assert "trend_id" in trend
        assert "title" in trend
        assert "timestamp" in trend
        assert "score" in trend