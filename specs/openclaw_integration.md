# Project Chimera — OpenClaw Integration Plan

## Overview
Project Chimera participates in the OpenClaw Agent Social Network as a specialized autonomous influencer agent.  
Its purpose is to discover other agents, advertise capabilities, and coordinate tasks while following strict safety, governance, and spec-driven rules.

---

## Agent Identity & Capabilities
- **Agent ID:** chimera_agent_v1
- **Capabilities:**
  - trend_discovery
  - content_generation
  - governance_review
  - content_publishing
- **Role Scope:** Each capability is mapped to a deterministic skill with clear input/output contracts.

---

## Status & Availability Signals
Chimera must broadcast its status to the network in a structured format:

| Field             | Type   | Description                                      |
|------------------|--------|-------------------------------------------------|
| agent_id          | string | Unique identifier of the agent                  |
| status            | string | 'available', 'busy', 'restricted', 'offline'   |
| active_skills     | list   | Currently active skills                         |
| last_heartbeat    | string | ISO 8601 timestamp of last status update       |
| pending_approvals | int    | Number of drafts awaiting human review         |

- Status updates must be sent at **regular intervals** or upon significant state changes.
- No skills may execute without a status update confirming availability.

---

## Capability Discovery Protocol
1. Chimera publishes a **capability advertisement** when a new skill is deployed.
2. Other agents may query Chimera using:
   - `query_capabilities(agent_id: str)` → returns active skills list
3. All capability requests and responses must be logged in MCP for traceability.

---

## Task Coordination
- **Shared Task Announcements:** Chimera may announce tasks it cannot complete alone.  
  Example: “I need human-reviewed content on trending topic X.”
- **Task Claiming Protocol:** Only agents with matching skills may claim tasks.  
- **Conflict Avoidance:**  
  - Multiple agents may not modify the same content draft.  
  - Attempted simultaneous execution triggers a **halt + escalation**.
- **Completion Reporting:**  
  - Agents must report task completion back to Chimera or network task broker.

---

## Instruction Validation
- Chimera must validate **incoming tasks** against:
  1. Spec-driven constraints (`specs/technical.md`)
  2. Governance rules (`specs/_meta.md`)
  3. Current agent status (availability, skills)
- Invalid or unsafe instructions must be **rejected and logged**, never executed.

---

## Logging & Traceability
- Every network communication (send, receive, claim, complete) is logged via MCP.
- Logs include:
  - timestamp
  - message type
  - agent_id of sender/receiver
  - task_id or draft_id if applicable
  - validation outcome
- These logs are critical for debugging multi-agent interactions and future audits.

---

## Security & Safety Considerations
- Communications must be encrypted and authenticated.
- Agents must **never accept arbitrary instructions** outside the approved spec.
- All interactions respect human-in-the-loop approvals.
- Unrecognized agent IDs or malformed messages are rejected by default.
