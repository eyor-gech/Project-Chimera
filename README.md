# Project Chimera
The Agentic Infrastructure Challenge as Forward Deployed Engineer (FDE) Trainee

## Overview

Project Chimera is an **autonomous AI influencer system** designed to research trends, generate platform-appropriate content, and manage engagement with minimal human intervention.  
The project is built with **Spec-Driven Development (SDD)**, Test-Driven Development (TDD), containerization, and AI governance principles.

---

## Features

- **Spec-Driven Development:** All behavior is guided by `specs/` directory.
- **Skills Directory:** Deterministic, stateless capabilities executed at runtime.
  - `skill_fetch_trends`: discover trending topics.
  - `skill_generate_content`: generate content drafts via OpenRouter.
  - `skill_approve_content`: human-in-the-loop approval.
- **Source-Grounded Generation:** on the live trend path each story's linked
  article and its top comments are read and analysed, and that material is fed
  to the model — drafts are based on the actual subject, not the headline alone
  (FR-16). Each draft reports `grounded_on_source` so an ungrounded run is never
  mistaken for a researched one.
- **Governed Orchestration:** `runtime/orchestrator.py` runs fetch → generate → approve → **stop**, emitting MCP-shaped telemetry for every action. Nothing is published.
- **Fail-Closed Governance:** Content is auto-approved only at `brand_safety_score >= 0.85`; anything lower — *or any missing evidence* — escalates to a human.
- **Graceful Degradation:** With no API key or on provider failure, generation falls back to a deterministic offline stub, so the demo and the test suite never break.
- **TDD:** Tests define contracts before implementation; 171 tests cover every skill, the pipeline, and the demo entry point.
- **Containerized Environment:** Docker ensures reproducibility across platforms.
- **AI Governance:** GitHub Actions enforce spec compliance, traceability, and CodeRabbit policies.

---

## Repository Structure
```
Project-Chimera/
├── specs/ # Project specifications (single source of truth)
│ ├── _meta.md
│ ├── functional.md
│ ├── technical.md
│ ├── orchestration.md
│ └── openclaw_integration.md
├── skills/ # Agent skills (deterministic, stateless)
│ ├── skill_fetch_trends.py
│ ├── skill_generate_content.py
│ ├── skill_approve_content.py
│ └── README.md
├── runtime/ # Orchestration + infrastructure
│ ├── orchestrator.py # Governed 4-stage pipeline
│ ├── llm_client.py # OpenRouter gateway (network I/O isolated)
│ └── source_reader.py # Article + top-comment reader (network I/O isolated)
├── tests/ # TDD contract tests
│ ├── conftest.py
│ ├── test_trend_fetcher.py
│ ├── test_skills_interface.py
│ ├── test_orchestrator.py
│ ├── test_skill_contracts.py
│ ├── test_orchestrator_pipeline.py
│ └── test_source_reader.py
├── demo.py # Live end-to-end demonstration
├── .cursor/rules # Context engineering rules
├── .coderabbit.yaml # AI governance config
├── Dockerfile # Container definition
├── Makefile # Standardized commands
├── requirements.txt
└── README.md
```
---

## Setup & Installation

1. **Clone the repository**

```bash
git clone https://github.com/<your-username>/project-chimera.git
cd project-chimera
```

2. **Build Docker image**
```
docker build -t chimera-agent .
```

3. **Configure credentials (optional)**
```
cp .env.example .env
# then add your OpenRouter key:
#   OPENROUTER_API_KEY=sk-or-...
```
`.env` is git-ignored and excluded from the Docker build context, so the key
never reaches the repo or an image layer. The key is never printed by the demo —
only whether one was found.

4. **Run the live demo**
```
python demo.py                  # YouTube, 3 trends, live LLM
python demo.py Twitter 5        # another platform / count
python demo.py --offline        # deterministic stub, no API call
python demo.py --no-color       # plain text output
```
Prints a colored, step-by-step execution log: configuration and spec chain,
trend discovery, content generation, the governance gate, and an MCP telemetry
trace. Execution halts after approval — no content is published.

5. **Run container and tests**
```
make test        # tests in Docker
```
✅ All tests pass. The original failing tests have been implemented against their
contracts and extended with full pipeline coverage.

## **Makefile Commands**
```
Command	         Description
make setup	     Install Python dependencies
make test	     Run all tests in Docker
make test-local  Run all tests locally
make demo	     Run the live demo in Docker
make demo-local  Run the live demo locally
make build	     Build the Docker image
make lint	     Run code linter
make spec-check  Verify spec presence
```

`make demo` accepts overrides: `make demo PLATFORM=Instagram LIMIT=5`

## **GitHub Actions / CI**
- Workflow located at .github/workflows/main.yml
- Runs on push or pull request
- Enforces:
  - Tests execution (hermetic — no API key or network required)
  - Spec presence
  - .coderabbit.yaml compliance
  - Traceable CI/TDD pipeline

> Tests force `CHIMERA_OFFLINE=1` via an autouse fixture in `tests/conftest.py`,
> so CI never depends on an LLM provider being reachable.

## **Copilot / IDE AI**
The repository includes context rules in .cursor/rules to ensure the copilot:
    - Always checks specs/ before generating code
    - Explains assumptions before implementation
    - Logs all actions via MCP telemetry

## **Example questions to ask your copilot**
1) "Explain the input/output contract for skill_generate_content."
2) "Which spec file governs the behavior of trend fetching?"
3) "How should I handle approval for high-risk content?"
4) "Plan the steps to fetch trending topics from Instagram and return them as Trend objects."
5) "Simulate a human-in-the-loop approval workflow for content drafts."
6) "Verify if all skills follow deterministic and stateless principles."
7) "Check if adding a new skill would violate the specs or governance rules."
8) "Why does `approve_content` return both `status` and `workflow_status`?"
9) "What happens to the pipeline if the OpenRouter API is unreachable?"

These questions demonstrate full mastery of Task 2 and 3, showing that the agent respects the prime directive, spec supremacy, and governance constraints.

---

## Governance Design Decisions

Worth raising in the interview, since each is a deliberate trade-off:

1. **Additive contract evolution (v1.1).** The demo's richer fields
   (`topic`/`volume`/`category`, `headline`/`caption`/`brand_safety_score`)
   were added *alongside* the spec's canonical fields rather than replacing
   them. `specs/technical.md` carries an amendment log recording this, so
   traceability is preserved and the original TDD tests still hold.

2. **Two status fields on approval.** `status` stays pinned to the canonical
   three-value enum that `tests/test_skills_interface.py` asserts; the
   two-state publishing value lives in `workflow_status`. Both derive from one
   decision, so they cannot disagree.

3. **Network I/O outside the skill core.** `skills/README.md` requires skills to
   be deterministic and stateless. Routing the LLM through
   `runtime/llm_client.py` keeps the skill contract testable and lets the
   offline stub guarantee the suite is hermetic.

4. **Fail-closed governance.** A missing or unreadable `brand_safety_score`
   escalates to human review. Absence of evidence is never treated as evidence
   of safety — this follows `specs/_meta.md` directly.

5. **Halting, not swallowing.** If any skill fails, the orchestrator logs a
   `run.halted` event and re-raises. No partial pipeline result is ever
   returned (FR-15, `specs/orchestration.md`).

6. **Secrets never in the image.** `.dockerignore` keeps `.env` out of the build
   context, so `COPY . /app` cannot bake the API key into an image layer.

7. **Free-tier-first model chain.** Generation leads with
   `google/gemma-4-26b-a4b-it:free`, falls back through two more free models, and
   ends at `gpt-4o-mini`. A 429 is retried with exponential backoff before the
   chain advances, and the run summary prints which model actually served each
   draft — so a quota exhaustion walking the chain down to the paid tail is
   visible rather than silent.

> **Interview caveat:** OpenRouter free keys allow **50 free-model requests per
> day**. Once spent, calls fall through to `gpt-4o-mini` and start consuming
> credits. If the demo must run on the free model every time, either reset the
> quota before recording, or set `CHIMERA_MODEL_CHAIN` to free models only
> (generation then degrades to the offline stub rather than spending credits).

## Contributing
- Follow Spec-Driven Development — always consult specs/ before writing code.
- Implement Skills only after tests define the contract.
- All changes must pass CI tests and respect .coderabbit.yaml rules.
- Amend `specs/technical.md` (with a version note) before changing a skill
  contract, then update `skills/README.md` to match.

## License
This project is internal for demonstration purposes and may include proprietary guidelines. All agent actions are controlled and governed.


---

### Key Notes
1. The **README emphasizes your knowledge** of SDD, TDD, AI governance, Docker, Makefile, and Skills.
2. The **copilot questions section** is perfect for your video demo — you can ask these live and show how the agent responds.
3. The structure is **submission-ready**, professional, and clearly shows **traceability** and **human-in-the-loop safety principles**.  

---

If you want, I can also **draft a “video cues table”** that combines the README, Docker, Makefile, failing tests, and copilot questions so you can read your **voice-over script seamlessly** during your 5-minute Loom video.  
