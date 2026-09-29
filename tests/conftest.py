"""Shared pytest configuration for Project Chimera.

Two jobs:

1. Put the repository root on ``sys.path`` so ``skills``/``runtime`` import
   cleanly regardless of the working directory pytest is launched from
   (important for ``make test`` inside Docker).
2. Force the deterministic offline stub for every test.

Point 2 is what makes the suite hermetic: ``make test`` must pass in CI and in
a Docker container with no ``OPENROUTER_API_KEY`` and no network access. Tests
that specifically exercise the live path re-enable it with ``monkeypatch``
inside the test body.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/ -> repository root
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    """Disable all LLM network access for the duration of every test."""
    monkeypatch.setenv("CHIMERA_OFFLINE", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    yield
