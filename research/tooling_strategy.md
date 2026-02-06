# Project Chimera — Tooling Strategy (Developer Tools / MCP Servers)

## Purpose
These tools help developers and the IDE agent work safely, track changes, and enforce traceability.

---

## MCP Servers (Developer Tools)

| Tool | Purpose | Notes |
|------|---------|-------|
| git-mcp | Version control for code & specs | Ensures commit history reflects evolving complexity |
| filesystem-mcp | Read/write access to repo | Allows agent to edit files safely and deterministically |
| logger-mcp | Telemetry logging | Records input/output of skills, errors, and speculative actions |
| secrets-mcp | Manage API keys / credentials | Provides secure storage without exposing secrets in code |
| test-runner-mcp | Executes unit tests | Runs failing tests as a baseline for TDD approach |

---

## Guidelines
- MCP tools must **always be called first** before analysis or code execution.
- All MCP interactions are **logged automatically** for audit and debugging.
- Developer tools **do not modify runtime agent behavior** — they are for safe environment control.
- New tools must be documented in `tooling_strategy.md` before use.
