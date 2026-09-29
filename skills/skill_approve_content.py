"""Skill 3 - Governance & Approval (Safety and Governance Agent).

Spec references
---------------
* ``specs/technical.md``  -> "Governance & Approval API" (canonical contract)
* ``specs/functional.md`` -> FR-7, FR-8, FR-9
* ``specs/_meta.md``      -> "Content classified as high-risk, ambiguous, or
  policy-uncertain must NOT be published" and "Any detected uncertainty ...
  must trigger escalation rather than execution"
* ``specs/orchestration.md`` -> "Orchestration must NOT bypass approval"

Contract (v1.1 - superset of the canonical spec and the demo contract)
---------------------------------------------------------------------
``approve_content(draft_id: str | None = None, draft: dict | None = None,
threshold: float = 0.85) -> dict``

Returned ``ApprovalStatus`` object:

    status             str    canonical spec enum: one of
                           'approved', 'rejected', 'needs_review'  [spec]
    workflow_status    str    publishing state: 'READY_FOR_PUBLISH' or
                           'NEEDS_HUMAN_REVIEW'                   [demo]
    approved           bool    gate decision                       [demo]
    reason             str    human-readable justification         [demo]
    reviewer_comments  str    same justification, spec field name  [spec]
    draft_id           str    reviewed draft                      [spec]
    brand_safety_score float   observed score, or -1.0 if unknown  [demo]
    threshold          float   applied gate                       [demo]
    evaluated_at       str    ISO 8601 evaluation timestamp       [audit]

Why two status fields
---------------------
``specs/technical.md`` fixes ``status`` to the three-value governance enum, and
``tests/test_skills_interface.py`` asserts exactly that. The publishing
pipeline needs the coarser two-state value, so it is exposed as
``workflow_status`` rather than overwriting the spec field. Both are derived
from the same single decision, so they can never disagree.

Governance stance
-----------------
The gate is *fail-closed*. A draft is only auto-approved when its
``brand_safety_score`` is known **and** at or above the threshold. If the
caller passes only a ``draft_id`` - with no score to inspect - the draft is
escalated to a human rather than assumed safe, per FR-7 and the escalation
rule in ``specs/_meta.md``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: Minimum automated brand safety score required for auto-approval.
DEFAULT_SAFETY_THRESHOLD: float = 0.85

#: Canonical governance enum from ``specs/technical.md``.
APPROVED = "approved"
REJECTED = "rejected"
NEEDS_REVIEW = "needs_review"

#: Publishing states used by the pipeline.
READY_FOR_PUBLISH = "READY_FOR_PUBLISH"
NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"

#: Reason strings (verbatim governance wording).
REASON_PASSED = "Passed automated brand safety thresholds."
REASON_FLAGGED = "Flagged for potential brand risk."
REASON_NO_EVIDENCE = "No brand safety evidence supplied for this draft; escalated to human."
REASON_INVALID_SCORE = "Draft carried an unreadable brand safety score; escalated to human."

#: Sentinel used when no score could be read from the draft.
UNKNOWN_SCORE = -1.0


class ApprovalError(ValueError):
    """Raised when the approval request itself is malformed (FR-13)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _coerce_score(draft: Dict[str, Any]) -> Optional[float]:
    """Read and clamp ``brand_safety_score`` from a draft.

    Returns ``None`` when the key is missing or unparseable, which the caller
    treats as "no evidence" and escalates.
    """
    raw = draft.get("brand_safety_score")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, score))


def _decide(score: Optional[float], threshold: float) -> Dict[str, Any]:
    """Apply the governance gate and build the decision fields.

    Fail-closed: only a known score at or above ``threshold`` is approved.
    """
    if score is None:
        return {
            "approved": False,
            "status": NEEDS_REVIEW,
            "workflow_status": NEEDS_HUMAN_REVIEW,
            "reason": REASON_NO_EVIDENCE,
        }

    if score >= threshold:
        return {
            "approved": True,
            "status": APPROVED,
            "workflow_status": READY_FOR_PUBLISH,
            "reason": REASON_PASSED,
        }

    return {
        "approved": False,
        "status": NEEDS_REVIEW,
        "workflow_status": NEEDS_HUMAN_REVIEW,
        "reason": REASON_FLAGGED,
    }


# --------------------------------------------------------------------------
# Skill entry point
# --------------------------------------------------------------------------

def approve_content(
    draft_id: Optional[str] = None,
    draft: Optional[Dict[str, Any]] = None,
    threshold: float = DEFAULT_SAFETY_THRESHOLD,
) -> Dict[str, Any]:
    """Run the brand safety gate on a content draft (FR-7, FR-8, FR-9).

    Args:
        draft_id: Identifier of the draft under review. May be supplied alone
            (canonical spec signature) or alongside ``draft``.
        draft: The draft payload. When present its ``brand_safety_score`` is
            the input to the gate; when absent the draft is escalated.
        threshold: Minimum score for auto-approval (default 0.85).

    Returns:
        An ``ApprovalStatus`` dict; see the module docstring for the key list.
        ``status`` is the canonical spec enum, ``workflow_status`` is the
        publishing state, and ``reason``/``reviewer_comments`` carry the same
        justification string.

    Raises:
        ApprovalError: ``MISSING_DRAFT_REFERENCE`` when neither ``draft_id``
            nor ``draft`` is supplied (FR-13: halt rather than assume).

    Example:
        >>> approve_content(draft_id="abc")["status"]
        'needs_review'
        >>> approve_content(draft={"brand_safety_score": 0.91})["workflow_status"]
        'READY_FOR_PUBLISH'
    """
    if not draft_id and not draft:
        raise ApprovalError(
            "MISSING_DRAFT_REFERENCE",
            "approve_content requires either a draft_id or a draft payload.",
        )

    if draft is not None and not isinstance(draft, dict):
        raise ApprovalError("INVALID_DRAFT", "draft must be a dict, got {!r}.".format(type(draft).__name__))

    score = _coerce_score(draft) if draft is not None else None
    decision = _decide(score, threshold)

    reason = decision["reason"]
    if draft is not None and score is None:
        reason = REASON_INVALID_SCORE

    return {
        # Canonical spec fields (specs/technical.md -> Governance & Approval API)
        "status": decision["status"],
        "reviewer_comments": reason,
        "draft_id": draft_id if draft_id else draft.get("draft_id"),
        # Gate decision (demo contract)
        "approved": decision["approved"],
        "workflow_status": decision["workflow_status"],
        "reason": reason,
        "brand_safety_score": score if score is not None else UNKNOWN_SCORE,
        "threshold": threshold,
        # Audit (FR-14: traceable agent actions)
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
