# Chimera Skill Orchestration Specification

## Purpose
Defines how Chimera coordinates skills in a deterministic, governed pipeline.

## Orchestration Flow
1. Fetch trends
2. Generate content drafts for each trend
3. Require human approval before any further action
4. Stop execution after approval stage

## Constraints
- Orchestration must NOT bypass approval
- Orchestration must be deterministic
- Orchestration must log every step via MCP

## Failure Handling
- If any skill fails, execution halts
- No partial publishing allowed

## Non-Goals
- No scheduling
- No autonomous publishing
- No parallel execution
