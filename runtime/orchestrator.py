"""Chimera Skill Orchestrator.

Spec references
---------------
* ``specs/orchestration.md`` -> deterministic, governed 4-stage flow
* ``specs/functional.md``    -> FR-1..FR-9, FR-13, FR-14, FR-15
* ``specs/_meta.md``         -> governance rules override performance goals

Flow (per ``specs/orchestration.md``)
------------------------------------
1. Fetch trends                     (Trend Research Agent)
2. Generate a draft per trend       (Content Generation Agent)
3. Run the governance gate          (Safety and Governance Agent)
4. **Stop.** No publishing happens here - ``publish_content`` is explicitly a
   non-goal of this stage, and ``specs/orchestration.md`` requires execution to
   halt after approval.

Telemetry (FR-14)
-----------------
Every stage emits an MCP-shaped event (``event``, ``agent``, ``stage``,
``timestamp``, plus the skill inputs/outputs) into :data:`TELEMETRY`. A
``logger`` callback can be supplied to stream those events live, which is what
``demo.py`` uses for its step-by-step output. The in-memory log is the
simulated MCP sink; a real deployment would post the same payloads to an MCP
server without changing this module's contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from skills.skill_approve_content import (
    DEFAULT_SAFETY_THRESHOLD,
    NEEDS_HUMAN_REVIEW,
    READY_FOR_PUBLISH,
    approve_content,
)
from skills.skill_fetch_trends import fetch_trends
from skills.skill_generate_content import generate_content

#: In-memory MCP telemetry sink (FR-14). Append-only within a process run.
TELEMETRY: List[Dict[str, Any]] = []

#: Agent role per pipeline stage (``specs/functional.md`` -> "Agent Roles").
STAGE_AGENTS: Dict[str, str] = {
    "trend_discovery": "Trend Research Agent",
    "content_generation": "Content Generation Agent",
    "governance_approval": "Safety and Governance Agent",
}

#: Stage ordering, referenced in telemetry for auditability.
STAGES: tuple = ("trend_discovery", "content_generation", "governance_approval")


def _emit(
    stage: str,
    event: str,
    logger: Optional[Callable[[Dict[str, Any]], None]] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """Append one MCP telemetry record and forward it to ``logger``.

    Args:
        stage: One of :data:`STAGES`.
        event: Short event name, e.g. ``"skill.completed"``.
        logger: Optional sink invoked with the same payload.
        **fields: Additional payload (inputs, outputs, error, ...).

    Returns:
        The recorded telemetry entry.
    """
    entry: Dict[str, Any] = {
        "event": event,
        "stage": stage,
        "agent": STAGE_AGENTS[stage],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    TELEMETRY.append(entry)

    if logger is not None:
        logger(entry)
    return entry


def run_chimera(
    platform: str,
    limit: int = 5,
    logger: Optional[Callable[[Dict[str, Any]], None]] = None,
    safety_threshold: float = DEFAULT_SAFETY_THRESHOLD,
    use_real_api: bool = False,
) -> Dict[str, Any]:
    """Run the governed Chimera pipeline end to end.

    Args:
        platform: Target platform - one of ``YouTube``, ``Twitter``,
            ``Instagram``.
        limit: Number of trends to discover (1-50).
        logger: Optional callback receiving each MCP telemetry entry, used by
            ``demo.py`` to print a live trace.
        safety_threshold: Governance gate applied by the approval skill.

    Returns:
        A dict with ``trends``, ``drafts``, ``approvals`` (the pipeline
        outputs), ``telemetry`` (this run's MCP events), and ``summary``
        (counts plus the ``publishable``/``escalated`` split).

    Raises:
        ValueError: propagated from the failing skill. Per
            ``specs/orchestration.md`` ("If any skill fails, execution halts")
            and FR-15 ("fail safely, avoid partial or irreversible actions"),
            the failure is logged to telemetry and re-raised rather than
            swallowed - no partial pipeline result is ever returned.
    """
    run_id = datetime.now(timezone.utc).isoformat()
    TELEMETRY.clear()
    _emit(
        "trend_discovery",
        "run.started",
        logger,
        run_id=run_id,
        inputs={"platform": platform, "limit": limit, "safety_threshold": safety_threshold},
        spec_refs=["FR-1", "FR-13", "FR-14"],
    )

    # -- Stage 1: Trend discovery (FR-1, FR-2) ---------------------------
    try:
        trends = fetch_trends(platform=platform, limit=limit, use_real_api=use_real_api)
    except Exception as exc:  # noqa: BLE001 - halt, log, escalate (FR-15)
        _emit("trend_discovery", "run.halted", logger, error=getattr(exc, "code", type(exc).__name__),
              message=str(exc), spec_refs=["FR-13", "FR-15"])
        raise
    _emit("trend_discovery", "skill.completed", logger, outputs=trends,
          count=len(trends), spec_refs=["FR-1", "FR-2"])

    # -- Stage 2: Content generation (FR-4, FR-5, FR-6) -------------------
    drafts: List[Dict[str, Any]] = []
    for trend in trends:
        try:
            draft = generate_content(
                trend_id=trend["trend_id"],
                topic=trend["topic"],
                platform=platform,
                context=trend.get("context"),
            )
        except Exception as exc:  # noqa: BLE001 - halt, log, escalate (FR-15)
            _emit("content_generation", "run.halted", logger, trend_id=trend["trend_id"],
                  error=getattr(exc, "code", type(exc).__name__), message=str(exc),
                  spec_refs=["FR-13", "FR-15"])
            raise
        drafts.append(draft)
        _emit("content_generation", "skill.completed", logger, trend_id=trend["trend_id"],
              output=draft, grounded_on_source=draft.get("grounded_on_source", False),
              spec_refs=["FR-4", "FR-5", "FR-6", "FR-16"])

    # -- Stage 3: Governance gate (FR-7, FR-8, FR-9) ----------------------
    approvals: List[Dict[str, Any]] = []
    for draft in drafts:
        try:
            approval = approve_content(draft_id=draft["draft_id"], draft=draft,
                                       threshold=safety_threshold)
        except Exception as exc:  # noqa: BLE001 - halt, log, escalate (FR-15)
            _emit("governance_approval", "run.halted", logger, draft_id=draft["draft_id"],
                  error=getattr(exc, "code", type(exc).__name__), message=str(exc),
                  spec_refs=["FR-13", "FR-15"])
            raise
        approvals.append(approval)
        _emit("governance_approval", "skill.completed", logger, draft_id=draft["draft_id"],
              output=approval, spec_refs=["FR-7", "FR-8", "FR-9"])

    # -- Stage 4: Stop (specs/orchestration.md) ---------------------------
    publishable = [a for a in approvals if a["workflow_status"] == READY_FOR_PUBLISH]
    escalated = [a for a in approvals if a["workflow_status"] == NEEDS_HUMAN_REVIEW]
    summary = {
        "run_id": run_id,
        "platform": platform,
        "trends": len(trends),
        "drafts": len(drafts),
        "approved": len(publishable),
        "escalated": len(escalated),
        "ready_for_publish": [a["draft_id"] for a in publishable],
        "needs_human_review": [a["draft_id"] for a in escalated],
        "live_llm_drafts": sum(1 for d in drafts if d["generation_mode"] == "live-llm"),
        "halted": False,
        "next_stage": "stopped_after_approval",
    }
    _emit("governance_approval", "run.completed", logger, outputs=summary,
          spec_refs=["FR-8", "FR-9", "FR-10"])

    return {
        "trends": trends,
        "drafts": drafts,
        "approvals": approvals,
        "telemetry": list(TELEMETRY),
        "summary": summary,
    }
