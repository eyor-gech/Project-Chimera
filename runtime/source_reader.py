"""Source reader - fetch and analyse a trend's content and top comments.

Spec references
---------------
* ``specs/functional.md`` -> FR-16 (v1.2): ground drafts in a trend's source
  material rather than the headline alone
* ``specs/technical.md``  -> Trend Discovery / Content Generation (v1.2)
* ``skills/README.md``    -> network I/O stays outside the skill core

Why this module exists
----------------------
``skills/skill_fetch_trends.py`` owns the *trend contract*; this module owns the
*network side effect* of reading a story's linked article and its top comments.
Keeping them apart mirrors ``runtime/llm_client.py`` and keeps the skills
unit-testable with no network access.

Every function here is failure-tolerant: a network error, a non-HTML response or
an unreadable page degrades to an empty result so the pipeline can fall back to
headline-only generation instead of crashing.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence

import requests

#: Hacker News Firebase API base - the default live trend source.
HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

#: Hacker News discussion page for an item.
HN_ITEM_URL = "https://news.ycombinator.com/item?id={item_id}"

#: Per-request timeout in seconds.
DEFAULT_TIMEOUT = 10.0

#: Character budgets keep the prompt bounded and each run predictable.
ARTICLE_MAX_CHARS = 1500
COMMENT_MAX_CHARS = 300
MAX_COMMENTS = 5
CONTEXT_MAX_CHARS = 4000

#: A browser-like user agent avoids trivial bot blocks on publishers.
_USER_AGENT = "ProjectChimera/1.0 (+https://github.com/anomalyco/project-chimera)"


class _TextExtractor(HTMLParser):
    """Collect visible text from an HTML fragment, skipping script/style."""

    _SKIP_TAGS = ("script", "style", "noscript", "template", "head")
    _BLOCK_TAGS = (
        "p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "article", "section", "blockquote", "pre",
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts)).strip()


def html_to_text(raw_html: str) -> str:
    """Return the visible text of an HTML fragment.

    Falls back to a tag-stripping regex if the parser chokes on malformed
    markup, so a broken page never raises into the pipeline.
    """
    if not raw_html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw_html)
        parser.close()
        return parser.text()
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_html)).strip()


def _clip(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` chars on a word boundary where possible."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0]
    return (clipped or text[: limit - 1]).rstrip() + "…"


def fetch_url_text(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Fetch a URL and return its visible text, or ``""`` on any failure.

    Non-text responses (images, PDFs) are ignored rather than mis-decoded.
    """
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type and "html" not in content_type and "text" not in content_type:
            return ""
        return html_to_text(response.text)
    except Exception:
        return ""


def fetch_hn_item_text(item_id: int, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Return the text body of a Hacker News item, or ``""`` on failure."""
    try:
        response = requests.get(f"{HN_API_BASE}/item/{item_id}.json", timeout=timeout)
        response.raise_for_status()
        item = response.json() or {}
        return html_to_text(item.get("text", ""))
    except Exception:
        return ""


def fetch_top_comments(
    comment_ids: Optional[Sequence[int]],
    *,
    limit: int = MAX_COMMENTS,
    timeout: float = DEFAULT_TIMEOUT,
) -> List[str]:
    """Read up to ``limit`` top-level comments for a story."""
    comments: List[str] = []
    for comment_id in list(comment_ids or [])[:limit]:
        text = fetch_hn_item_text(comment_id, timeout=timeout)
        if text:
            comments.append(_clip(text, COMMENT_MAX_CHARS))
    return comments


def build_source_context(
    item: Dict[str, Any], *, timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """Read a story's article/self text and top comments into a context block.

    Args:
        item: A Hacker News item dict (``url``, ``text``, ``id``, ``kids``).
        timeout: Per-request timeout in seconds.

    Returns:
        ``{"context": str, "source_url": str, "comments": int}``. ``context`` is
        the text handed to the generator; it is ``""`` when nothing could be
        read, which signals the caller to fall back to headline-only.
    """
    source_url = item.get("url") or HN_ITEM_URL.format(item_id=item.get("id"))
    if item.get("url"):
        article = fetch_url_text(item["url"], timeout=timeout)
    else:
        article = html_to_text(item.get("text", ""))

    comments = fetch_top_comments(item.get("kids"), timeout=timeout)

    blocks: List[str] = []
    if article:
        blocks.append("Source content:\n" + _clip(article, ARTICLE_MAX_CHARS))
    if comments:
        blocks.append("Top comments:\n- " + "\n- ".join(comments))

    return {
        "context": _clip("\n\n".join(blocks), CONTEXT_MAX_CHARS),
        "source_url": source_url or "",
        "comments": len(comments),
    }
