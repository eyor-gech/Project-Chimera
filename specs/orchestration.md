# Chimera Skill Orchestration Specification

## Purpose
Defines how Chimera coordinates skills in a deterministic, governed pipeline.

## Orchestration Flow
1. Fetch trends
2. Generate content drafts for each trend
3. Require human approval before any further action
4. Stop execution after approval stage

**Implementation:** `runtime/orchestrator.py` → `run_chimera(platform, limit, logger, safety_threshold)`

The orchestrator returns `trends`, `drafts`, `approvals`, `telemetry` and
`summary`. Execution halts after stage 3 — `publish_content` is a non-goal of
this pipeline and is never invoked.

## Telemetry (FR-14)
Every stage emits an MCP-shaped event carrying `event`, `stage`, `agent`,
`timestamp` and `spec_refs` (the FR-X clauses it satisfies), appended to the
in-memory `TELEMETRY` sink. A `logger` callback streams the same payloads live;
`demo.py` uses it for the step-by-step terminal trace. Swapping the in-memory
sink for a real MCP server is an infrastructure change that leaves this
contract untouched.

## Constraints
- Orchestration must NOT bypass approval
- Orchestration must be deterministic
- Orchestration must log every step via MCP
- Orchestration must NOT publish (non-goal; stop after approval)

## Failure Handling
- If any skill fails, execution halts
- No partial publishing allowed

## Non-Goals
- No scheduling
- No autonomous publishing
- No parallel execution
