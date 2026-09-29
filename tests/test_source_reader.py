"""Tests for ``runtime/source_reader.py`` (v1.2 source grounding).

Spec references
---------------
* ``specs/functional.md`` -> FR-16: ground drafts in the trend's source
  material, not the headline alone
* ``skills/README.md``    -> network I/O stays outside the skill core
"""

from __future__ import annotations

import runtime.source_reader as sr


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, text="", payload=None, content_type="text/html; charset=utf-8"):
        self.text = text
        self._payload = payload
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestHtmlToText:
    def test_strips_tags(self):
        assert sr.html_to_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_drops_script_and_style_content(self):
        html = "<style>.a{color:red}</style><script>evil()</script><p>Visible</p>"
        assert sr.html_to_text(html) == "Visible"

    def test_collapses_whitespace(self):
        assert sr.html_to_text("<p>a\n\n   b</p>") == "a b"

    def test_unescapes_entities(self):
        assert "AT&T" in sr.html_to_text("<p>AT&amp;T</p>")

    def test_empty_input(self):
        assert sr.html_to_text("") == ""


class TestFetchUrlText:
    def test_returns_visible_text(self, monkeypatch):
        monkeypatch.setattr(
            sr.requests, "get",
            lambda *a, **k: FakeResponse("<html><body><p>Body text</p></body></html>"),
        )
        assert sr.fetch_url_text("https://example.com") == "Body text"

    def test_ignores_non_text_responses(self, monkeypatch):
        monkeypatch.setattr(
            sr.requests, "get",
            lambda *a, **k: FakeResponse("<pdf/>", content_type="application/pdf"),
        )
        assert sr.fetch_url_text("https://example.com/file.pdf") == ""

    def test_network_error_degrades_to_empty(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(sr.requests, "get", boom)
        assert sr.fetch_url_text("https://example.com") == ""


class TestFetchTopComments:
    def test_reads_and_clips_comments(self, monkeypatch):
        monkeypatch.setattr(
            sr.requests, "get",
            lambda *a, **k: FakeResponse("", payload={"text": "<p>Long comment body</p>"}),
        )
        comments = sr.fetch_top_comments([1, 2], limit=2)
        assert len(comments) == 2
        assert all(c.startswith("Long comment body") for c in comments)

    def test_respects_limit(self, monkeypatch):
        monkeypatch.setattr(
            sr.requests, "get",
            lambda *a, **k: FakeResponse("", payload={"text": "<p>c</p>"}),
        )
        assert len(sr.fetch_top_comments([1, 2, 3, 4, 5, 6], limit=2)) == 2

    def test_skips_empty_comments(self, monkeypatch):
        monkeypatch.setattr(
            sr.requests, "get",
            lambda *a, **k: FakeResponse("", payload={"text": ""}),
        )
        assert sr.fetch_top_comments([1, 2]) == []

    def test_network_error_skips_comment(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(sr.requests, "get", boom)
        assert sr.fetch_top_comments([1]) == []


class TestBuildSourceContext:
    def test_combines_article_and_comments(self, monkeypatch):
        monkeypatch.setattr(sr, "fetch_url_text", lambda *a, **k: "Article body")
        monkeypatch.setattr(sr, "fetch_top_comments", lambda *a, **k: ["First comment"])

        ctx = sr.build_source_context(
            {"id": 1, "url": "https://example.com/a", "kids": [10]}
        )

        assert "Article body" in ctx["context"]
        assert "First comment" in ctx["context"]
        assert ctx["source_url"] == "https://example.com/a"
        assert ctx["comments"] == 1

    def test_uses_self_text_when_no_url(self, monkeypatch):
        monkeypatch.setattr(sr, "fetch_top_comments", lambda *a, **k: [])

        ctx = sr.build_source_context({"id": 2, "text": "<p>Ask HN: body</p>", "kids": []})

        assert "Ask HN: body" in ctx["context"]
        assert ctx["source_url"].endswith("id=2")

    def test_degrades_to_empty_context_when_nothing_readable(self, monkeypatch):
        monkeypatch.setattr(sr, "fetch_url_text", lambda *a, **k: "")
        monkeypatch.setattr(sr, "fetch_top_comments", lambda *a, **k: [])

        ctx = sr.build_source_context(
            {"id": 3, "url": "https://example.com", "kids": [1]}
        )

        assert ctx["context"] == ""
        assert ctx["comments"] == 0

    def test_never_raises_on_network_failure(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(sr.requests, "get", boom)

        ctx = sr.build_source_context(
            {"id": 4, "url": "https://example.com", "kids": [1, 2]}
        )

        assert ctx["context"] == ""

    def test_context_is_bounded(self, monkeypatch):
        monkeypatch.setattr(sr, "fetch_url_text", lambda *a, **k: "word " * 20000)
        monkeypatch.setattr(sr, "fetch_top_comments", lambda *a, **k: [])

        ctx = sr.build_source_context({"id": 5, "url": "https://example.com"})

        assert len(ctx["context"]) <= sr.CONTEXT_MAX_CHARS
