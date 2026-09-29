IMAGE_NAME=chimera-agent
PLATFORM ?= YouTube
LIMIT ?= 3

# Address the container uses to reach Ollama running on the host. Overrides the
# host-side value in .env (`127.0.0.1`), which the container cannot resolve.
DOCKER_OLLAMA_URL ?= http://host.docker.internal:11434/v1

# pip flags for `make setup`. On PEP 668 "externally managed" systems a user
# install needs --break-system-packages; override with PIP_FLAGS="" for a venv.
PIP_FLAGS ?= --user --break-system-packages

.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make build        Build Docker image"
	@echo "  make setup        Install Python dependencies locally"
	@echo "  make test         Run tests in Docker"
	@echo "  make test-local   Run tests locally (no Docker)"
	@echo "  make demo         Run the live demo in Docker"
	@echo "  make demo-local   Run the live demo locally"
	@echo "  make lint         Placeholder for linting"
	@echo "  make spec-check   Verify spec presence"

.PHONY: build
build:
	docker build -t $(IMAGE_NAME) .

.PHONY: setup
setup:
	python3 -m pip install $(PIP_FLAGS) -r requirements.txt

.PHONY: test
test:
	docker run --rm $(IMAGE_NAME)

.PHONY: test-local
test-local:
	pytest tests/ -v

.PHONY: demo
demo: build
	docker run --rm -it --env-file .env -e CHIMERA_OPENROUTER_BASE_URL=$(DOCKER_OLLAMA_URL) --add-host=host.docker.internal:host-gateway $(IMAGE_NAME) python demo.py $(PLATFORM) $(LIMIT)

.PHONY: demo-local
demo-local:
	python3 demo.py $(PLATFORM) $(LIMIT)

.PHONY: lint
lint:
	python3 -m compileall -q skills runtime demo.py tests
	@echo "✅ Syntax check passed"

.PHONY: spec-check
spec-check:
	test -d specs || (echo "❌ specs/ directory missing" && exit 1)
	@echo "✅ specs/ directory present"

.PHONY: run
run:
	docker run --rm -it $(IMAGE_NAME)

.PHONY: streamlit
streamlit: build
	docker run --rm -it -p 8501:8501 --env-file .env -e CHIMERA_OPENROUTER_BASE_URL=$(DOCKER_OLLAMA_URL) -e STREAMLIT_BROWSER_GATHER_USAGE_STATS=false -e STREAMLIT_SERVER_HEADLESS=true --add-host=host.docker.internal:host-gateway $(IMAGE_NAME) streamlit run app.py --server.address=0.0.0.0

