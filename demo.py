#!/usr/bin/env python3
"""Project Chimera - live end-to-end demonstration.

Run it with::

    python demo.py                # YouTube, 3 trends
    python demo.py Twitter 5      # another platform / trend count
    python demo.py YouTube 3 --offline

What it shows, in order:
  0. Configuration and spec references (traceability)
  1. Trend discovery          (Trend Research Agent)
  2. Content generation       (Content Generation Agent)
  3. Governance approval      (Safety and Governance Agent)
  4. Run summary + MCP telemetry trace

Design notes
------------
* Colour is plain ANSI (``print`` formatting), so the demo has **no extra
  dependency** and renders identically in a terminal, in Docker and over SSH.
* ``--no-color`` and ``NO_COLOR`` / non-TTY output disable styling, so piping
  the demo to a file produces clean plain text.
* Credentials are read from ``.env`` via ``python-dotenv``; the key is never
  printed, only whether one was found.
* Execution stops after the approval stage, per
  ``specs/orchestration.md``: nothing is published.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List

try:  # python-dotenv is a declared dependency, but keep the demo runnable
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

from runtime.llm_client import get_client
from runtime.orchestrator import run_chimera
from skills.skill_approve_content import DEFAULT_SAFETY_THRESHOLD
from skills.skill_fetch_trends import SUPPORTED_PLATFORMS


# --------------------------------------------------------------------------
# ANSI styling
# --------------------------------------------------------------------------

class Style:
    """Minimal ANSI helper with a global on/off switch."""

    _CODES = {
        "reset": "0",
        "bold": "1",
        "dim": "2",
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
        "magenta": "35",
        "cyan": "36",
        "grey": "90",
    }

    enabled = True

    @classmethod
    def paint(cls, text: str, *styles: str) -> str:
        if not cls.enabled or not styles:
            return text
        codes = ";".join(cls._CODES[s] for s in styles if s in cls._CODES)
        return "\033[{}m{}\033[0m".format(codes, text) if codes else text

    @classmethod
    def disable(cls) -> None:
        cls.enabled = False


def banner(title: str, subtitle: str = "") -> None:
    """Print a section banner."""
    line = "=" * 78
    print(Style.paint(line, "cyan"))
    print(Style.paint(title, "bold", "cyan"))
    if subtitle:
        print(Style.paint(subtitle, "grey"))
    print(Style.paint(line, "cyan"))


def step(index: int, total: int, title: str) -> None:
    """Print a numbered step header."""
    tag = Style.paint(" STEP {}/{} ".format(index, total), "bold", "magenta")
    print("\n{} {}".format(tag, Style.paint(title, "bold")))


def kv(key: str, value: str, width: int = 26) -> None:
    """Print an aligned key/value line."""
    print("   {} {}".format(Style.paint(key.ljust(width), "grey"), value))


def rule() -> None:
    print(Style.paint("-" * 78, "grey"))


def format_volume(value: int) -> str:
    """Render a search-volume proxy compactly, e.g. ``184000`` -> ``184.0K``."""
    return "{:.1f}K".format(value / 1000) if value >= 1000 else str(value)


def score_color(score: float, threshold: float) -> str:
    """Green at/above the gate, yellow just under, red well under."""
    if score >= threshold:
        return "green"
    if score >= threshold - 0.1:
        return "yellow"
    return "red"


# --------------------------------------------------------------------------
# Telemetry renderer (FR-14: every agent action is traceable)
# --------------------------------------------------------------------------

#: Per-stage headings, printed the first time each stage reports in.
STAGE_HEADINGS: Dict[str, Any] = {
    "trend_discovery": (
        1, "Trend Discovery — Trend Research Agent  (FR-1, FR-2)",
        "Normalised and scored so trends can be ranked and compared.",
    ),
    "content_generation": (
        2, "Content Generation — Content Generation Agent  (FR-4, FR-5, FR-6)",
        "Drafts adapted to platform format, length and tone limits.",
    ),
    "governance_approval": (
        3, "Governance Approval — Safety and Governance Agent  (FR-7, FR-8, FR-9)",
        "Fail-closed gate: no safety evidence means no auto-approval.",
    ),
}


def make_logger():
    """Return a telemetry callback that streams each event as it happens.

    The pipeline emits events as it executes, so the demo prints a genuine
    step-by-step trace rather than a summary printed at the end. Each stage
    heading is emitted lazily, the first time that stage reports, so the log
    stays interleaved with real work rather than being pre-announced.
    """
    seen_stages: set = set()

    def _log(entry: Dict[str, Any]) -> None:
        event = entry.get("event", "")
        stage = entry.get("stage", "")

        if stage in STAGE_HEADINGS and stage not in seen_stages:
            seen_stages.add(stage)
            index, title, caption = STAGE_HEADINGS[stage]
            step(index, 4, title)
            print("   {}".format(Style.paint(caption, "grey")))

        if event == "run.started":
            print("   {} {}".format(Style.paint("▶", "blue"),
                                    Style.paint("run started", "blue")))

        elif event == "skill.completed" and entry.get("stage") == "trend_discovery":
            for trend in entry.get("outputs", []):
                print("   {} {} {}  {}  {}".format(
                    Style.paint("✔", "green"),
                    Style.paint(trend["trend_id"][:8], "grey"),
                    Style.paint(trend["topic"].ljust(32), "bold"),
                    Style.paint("score {:.2f}".format(trend["score"]).ljust(11), "cyan"),
                    Style.paint("{} · {} · {} vol".format(
                        trend["platform"], trend["category"],
                        format_volume(trend["volume"])), "grey"),
                ))

        elif event == "skill.completed" and entry.get("stage") == "content_generation":
            draft = entry["output"]
            print("   {} {} {}".format(
                Style.paint("✔", "green"),
                Style.paint(draft["headline"][:58].ljust(58), "bold"),
                Style.paint("[{}]".format(draft["generation_mode"]), "grey"),
            ))
            print("     {} {}".format(
                Style.paint(draft["caption"][:74].ljust(74), "grey"),
                Style.paint(" ".join(draft["suggested_hashtags"][:4]), "blue"),
            ))

        elif event == "skill.completed" and entry.get("stage") == "governance_approval":
            approval = entry["output"]
            passed = approval["approved"]
            badge = Style.paint("APPROVED", "bold", "green") if passed else Style.paint("ESCALATED", "bold", "yellow")
            print("   {} {} {} {}".format(
                Style.paint("✔" if passed else "▲", "green" if passed else "yellow"),
                badge,
                Style.paint(approval["workflow_status"], "cyan"),
                Style.paint("· score {:.2f} (gate {:.2f})".format(
                    approval["brand_safety_score"], approval["threshold"]), "grey"),
            ))
            print("     {}".format(Style.paint(approval["reason"], "grey")))

        elif event == "run.halted":
            print("   {} {} {}".format(
                Style.paint("✖", "red"),
                Style.paint("HALTED", "bold", "red"),
                Style.paint("{} — {}".format(entry.get("error"), entry.get("message")), "red"),
            ))

        elif event == "run.completed":
            print("   {} {}".format(
                Style.paint("■", "cyan"),
                Style.paint("run complete · halting after approval stage "
                            "(specs/orchestration.md)", "cyan"),
            ))

    return _log


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def print_preflight(platform: str, limit: int) -> None:
    """Print configuration, credentials state and the spec chain."""
    banner("PROJECT CHIMERA — AUTONOMOUS AI INFLUENCER SYSTEM",
           "Spec-Driven Development · Skill Orchestration · Human-in-the-Loop Governance")

    client = get_client()
    mode = (Style.paint("live LLM", "bold", "green") if client.is_available
            else Style.paint("offline deterministic stub", "bold", "yellow"))

    step(0, 4, "Configuration & spec references")
    kv("Target platform", Style.paint(platform, "bold") + Style.paint(
        "  (approved: {})".format(", ".join(SUPPORTED_PLATFORMS)), "grey"))
    kv("Trends requested", str(limit))
    kv("Governance gate", "brand_safety_score ≥ {:.2f}".format(DEFAULT_SAFETY_THRESHOLD))
    kv("API key (.env)", Style.paint("loaded", "green") if client.api_key
       else Style.paint("not found → using offline stub", "yellow"))
    kv("Execution mode", mode)
    kv("Model chain", Style.paint(" → ".join(client.model_chain), "cyan"))
    if not client.is_available:
        print("   {}".format(Style.paint(
            "Free-tier quota is exhausted — drafts will fall back to the "
            "offline stub, or the paid tail of the chain if credits allow.",
            "yellow")))
    kv("Spec chain", Style.paint(
        "specs/_meta.md → functional.md (FR-1..FR-15) → technical.md → orchestration.md", "grey"))


def print_summary(result: Dict[str, Any], elapsed: float) -> None:
    """Print the run summary and the publishing split."""
    summary = result["summary"]
    step(4, 4, "Run Summary & Traceability")

    rule()
    kv("Run id", summary["run_id"])
    kv("Trends discovered", str(summary["trends"]))
    kv("Drafts generated", "{} ({} live LLM)".format(
        summary["drafts"], summary["live_llm_drafts"]))
    kv("Approved", Style.paint(str(summary["approved"]), "bold", "green"))
    kv("Escalated to human", Style.paint(str(summary["escalated"]), "bold", "yellow"))
    kv("Wall clock", "{:.2f}s".format(elapsed))
    rule()

    # Surface which models actually served the drafts: a free-tier quota
    # exhaustion silently walks the chain down to the paid tail, and that must
    # be visible rather than hidden behind "live-llm".
    served = {}
    for draft in result["drafts"]:
        served[draft["generated_by"]] = served.get(draft["generated_by"], 0) + 1
    if served:
        print("\n   {}".format(Style.paint("Served by", "bold")))
        for model, count in served.items():
            paid = ":free" not in model and model != "offline-deterministic-stub"
            label = Style.paint(model, "yellow" if paid else "cyan")
            note = Style.paint("  (paid — free tier unavailable)", "yellow") if paid else ""
            print("      {} {} x {}{}".format(Style.paint("·", "cyan"), label, count, note))

    if summary["ready_for_publish"]:
        print("\n   {}".format(Style.paint("READY FOR PUBLISH", "bold", "green")))
        for draft_id in summary["ready_for_publish"]:
            print("      {} {}".format(Style.paint("→", "green"), draft_id))
    if summary["needs_human_review"]:
        print("\n   {}".format(Style.paint("NEEDS HUMAN REVIEW", "bold", "yellow")))
        for draft_id in summary["needs_human_review"]:
            print("      {} {}".format(Style.paint("→", "yellow"), draft_id))

    print("\n   {}".format(Style.paint("MCP telemetry events: ", "grey")
                           + str(len(result["telemetry"]))))
    for entry in result["telemetry"][:4]:
        print("      {} {} {} {}".format(
            Style.paint(entry["timestamp"][11:19], "grey"),
            Style.paint(entry["stage"].ljust(20), "cyan"),
            Style.paint(entry["event"].ljust(18), "blue"),
            Style.paint(entry.get("spec_refs", ""), "grey"),
        ))
    if len(result["telemetry"]) > 4:
        print(Style.paint("      … {} more events (full trace in the run summary)"
                          .format(len(result["telemetry"]) - 4), "grey"))

    print("\n" + Style.paint(
        "Execution halted after the approval stage — publishing is out of scope "
        "for this run (specs/orchestration.md).", "cyan"))


def print_governance_drill() -> None:
    """Demonstrate the escalation branch with a deliberately unsafe draft.

    The live run exercises whichever branch the generated scores produce; this
    drill makes the fail-closed behaviour explicit and reproducible for the
    interview, without touching the pipeline result.
    """
    from skills.skill_approve_content import approve_content

    rule()
    print("\n   {}".format(Style.paint("GOVERNANCE DRILL — fail-closed gate", "bold")))
    for score, label in ((0.97, "high-signal draft"), (0.86, "borderline draft"),
                         (0.41, "unsafe draft")):
        approval = approve_content(draft_id="drill-{}".format(score),
                                   draft={"brand_safety_score": score})
        colour = score_color(score, DEFAULT_SAFETY_THRESHOLD)
        print("      {} {:<18} score {:.2f}  {:<19} {}".format(
            Style.paint("·", colour),
            label,
            score,
            Style.paint(approval["workflow_status"], colour),
            Style.paint(approval["reason"], "grey"),
        ))
    escalation = approve_content(draft_id="drill-no-evidence")
    print("      {} {:<18} score  n/a  {:<19} {}".format(
        Style.paint("·", "red"), "no evidence",
        Style.paint(escalation["workflow_status"], "red"),
        Style.paint(escalation["reason"], "grey"),
    ))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse CLI arguments: platform, limit and display flags."""
    parser = argparse.ArgumentParser(
        description="Project Chimera end-to-end demonstration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("platform", nargs="?", default="YouTube", choices=list(SUPPORTED_PLATFORMS),
                        help="target platform (default: YouTube)")
    parser.add_argument("limit", nargs="?", type=int, default=3,
                        help="number of trends to process (default: 3)")
    parser.add_argument("--offline", action="store_true",
                        help="force the deterministic offline stub (no API call)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    return parser.parse_args(argv)


def main(argv: List[str] = None) -> int:
    """Run the demo. Returns a process exit code."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.no_color or os.getenv("NO_COLOR") or not sys.stdout.isatty():
        Style.disable()

    # Load .env for OPENROUTER_API_KEY before the client reads the environment.
    load_dotenv()

    if args.offline:
        os.environ["CHIMERA_OFFLINE"] = "1"

    print_preflight(args.platform, args.limit)

    started = time.perf_counter()
    try:
        result = run_chimera(platform=args.platform, limit=args.limit,
                             logger=make_logger())
    except Exception as exc:  # noqa: BLE001 - demo must fail visibly, not silently
        code = getattr(exc, "code", type(exc).__name__)
        print("\n{} {}".format(
            Style.paint("PIPELINE HALTED", "bold", "red"),
            Style.paint("[{}] {}".format(code, exc), "red"),
        ))
        print(Style.paint(
            "Execution halted per specs/orchestration.md — no partial results "
            "were published (FR-15).", "red"))
        return 1

    print_summary(result, time.perf_counter() - started)
    print_governance_drill()

    print("\n" + Style.paint("Demo complete. No content was published.", "bold", "cyan"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
