IMAGE_NAME=chimera-agent

.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make build        Build Docker image"
	@echo "  make test         Run tests in Docker"
	@echo "  make lint         Placeholder for linting"
	@echo "  make spec-check   Verify spec presence"

.PHONY: build
build:
	docker build -t $(IMAGE_NAME) .

.PHONY: test
test:
	docker run --rm $(IMAGE_NAME)

.PHONY: lint
lint:
	@echo "Linting not enforced yet (spec-driven phase)"

.PHONY: spec-check
spec-check:
	test -d specs || (echo "❌ specs/ directory missing" && exit 1)
	@echo "✅ specs/ directory present"

.PHONY: run
run:
	docker run --rm -it $(IMAGE_NAME)

