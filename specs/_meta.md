# Project Chimera = Meta Specification

## Purpose
Project Chimera exists to operate as an autonomous AI influencer system that identifies trending topics, generate platform-approriate content and manages engagement workflows under defined governance and safety constraints.

## Vision
Project Chimera is a long-running autonomous system that continuously monitors trends, produces compliant content tailored to specific platforms, and coordinates publishing actions with minimal human intervention while maintaining traceability, reliability and safety.

## Non-Goals
- Project Chimera is NOT a general-purpose conversational chatbot.
- Project Chimera does NOT redefine, override, or self-modify its own specifications.
- Project Chimera does NOT publish any content without passing governance and approval checks.
- Project Chimera does NOT independently set its own objectives beyond those defined in specs/.

## Operating Priniciples
- Spec-Driven Development is mandatory which is specifications are the single source of truth.
- All agent actions must be observable and traceable through MCP telemetry.
- Agent responsibilities must be explicit and role-scoped.
- Skills must be stateless, deterministic, and side-effect controlled.
- Ambiguity must result in a halt and request for clarification, NOT autonomous assumption.

## Safety & Governance Constraints
- Human approval is required for all newly identified trends before content generations.
- Content classified as high-risk, ambiguous, or policy-uncertain must NOT be published.
- Any detected uncertainty in compliance, realism, relevance must trigger escalation rather than execution.
- Governance rules take precedence over performance or engagement goals.

## Out of Scope
- Model training, fine-tuning, or weight modification.
- Autonomous configuration of user interfaces or dashboards.
- Publishing to platforms NOT explicitly defined in specifications.
- Monetization logic, analytics optimization, or growth-hacking strategies.

## Success Criteria
- All required specifications are complete, explicit, and internally consistent.
- Failing tests accurately define unimplemented behavior and pass only when contracts are satisfied.
- CI enforcement prevents merges that violate specs or governance rules.
- Agents interacting with the repository demonstrate adherence to the defined rules and constraints.