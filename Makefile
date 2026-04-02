# Makefile for GIMR development
# Usage: make build | make up | make logs | make clean

# Enable Docker BuildKit for faster builds
export DOCKER_BUILDKIT := 1
export COMPOSE_DOCKER_CLI_BUILD := 1

# Development environment
.PHONY: build
build:
	cd deploy && docker-compose build
	docker build -f deploy/Dockerfile.worker -t gimr-worker:latest ..

.PHONY: up
up:
	cd deploy && docker-compose up -d --build

.PHONY: down
down:
	cd deploy && docker-compose down

.PHONY: logs
logs:
	cd deploy && docker-compose logs -f

.PHONY: ps
ps:
	cd deploy && docker-compose ps

.PHONY: clean
clean:
	cd deploy && docker-compose down -v --rmi local

# Rebuild specific service (e.g., make rebuild-backend)
rebuild-%:
	cd deploy && docker-compose build $(shell echo $* | sed 's/_/-/g')
	cd deploy && docker-compose up -d $(shell echo $* | sed 's/_/-/g')

# ---- E2E Tests ----
.PHONY: e2e-up
e2e-up:
	cd deploy && docker-compose -f docker-compose.e2e.yml up -d --build

.PHONY: e2e-test
e2e-test:
	cd deploy && docker-compose -f docker-compose.e2e.yml run --rm e2e

.PHONY: e2e-test-specific
e2e-test-specific:
	cd deploy && docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/$(TEST_FILE) -v

.PHONY: e2e-down
e2e-down:
	cd deploy && docker-compose -f docker-compose.e2e.yml down

.PHONY: e2e-logs
e2e-logs:
	cd deploy && docker-compose -f docker-compose.e2e.yml logs -f

# Usage: make e2e-test-specific TEST_FILE=test_dashboard.py
.PHONY: e2e
e2e: e2e-up e2e-test e2e-down

# ---- Unit Tests ----
.PHONY: test-backend
test-backend:
	cd backend && python -m pytest tests/unit/ -v

.PHONY: test-frontend
test-frontend:
	cd frontend && npx vitest run

.PHONY: test-mock-e2e
test-mock-e2e:
	cd backend && python -m pytest tests/mock_e2e/ -v

.PHONY: test-gitlab-e2e
test-gitlab-e2e:
	cd backend && python -m pytest tests/gitlab_e2e/ -v

# Run all tests except Playwright E2E
.PHONY: test
test: test-backend test-frontend test-mock-e2e

# Run ALL tests including Playwright E2E (requires Docker)
# This starts E2E environment, runs all tests, then cleans up
.PHONY: test-all
test-all: test-backend test-frontend test-mock-e2e test-gitlab-e2e e2e
