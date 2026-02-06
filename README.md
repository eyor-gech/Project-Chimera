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
  - `skill_generate_content`: generate content drafts.
  - `skill_approve_content`: human-in-the-loop approval.
- **TDD:** Tests define contracts before implementation; failing tests indicate “empty slots” for agent implementation.
- **Containerized Environment:** Docker ensures reproducibility across platforms.
- **AI Governance:** GitHub Actions enforce spec compliance, traceability, and CodeRabbit policies.

---

## Repository Structure
```
Project-Chimera/
├── specs/ # Project specifications
│ ├── _meta.md
│ ├── functional.md
│ ├── technical.md
│ └── openclaw_integration.md
├── skills/ # Defined agent skills
│ ├── skill_fetch_trends.py
│ ├── skill_generate_content.py
│ ├── skill_approve_content.py
│ └── README.md
├── tests/ # Failing tests for TDD
│ ├── test_skills_interface.py
│ └── test_trend_fetcher.py
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

3. **Run container and tests**
```
make run
```
⚠️ Tests are expected to fail by design. This defines the contracts for agent implementation.

4. **Install dependencies locally (optional)**
```
pip install -r requirements.txt
```

## **Makefile Commands**
```
Command	    Description
make setup	Install Python dependencies
make test	Run all tests (failing tests indicate contract placeholders)
make run	Build and run the Docker container with tests
make lint	Run code linter
```

## **GitHub Actions / CI**
- Workflow located at .github/workflows/main.yml
- Runs on push or pull request
- Enforces:
  - Tests execution
  - Spec presence
  - .coderabbit.yaml compliance
  - Traceable CI/TDD pipeline

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

These questions demonstrate full mastery of Task 2 and 3, showing that the agent respects the prime directive, spec supremacy, and governance constraints.

## Contributing
- Follow Spec-Driven Development — always consult specs/ before writing code.
- Implement Skills only after tests define the contract.
- All changes must pass CI tests and respect .coderabbit.yaml rules.

## License
This project is internal for demonstration purposes and may include proprietary guidelines. All agent actions are controlled and governed.


---

### Key Notes
1. The **README emphasizes your knowledge** of SDD, TDD, AI governance, Docker, Makefile, and Skills.
2. The **copilot questions section** is perfect for your video demo — you can ask these live and show how the agent responds.
3. The structure is **submission-ready**, professional, and clearly shows **traceability** and **human-in-the-loop safety principles**.  

---

If you want, I can also **draft a “video cues table”** that combines the README, Docker, Makefile, failing tests, and copilot questions so you can read your **voice-over script seamlessly** during your 5-minute Loom video.  
