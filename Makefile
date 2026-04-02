# Makefile for GIMR
# ============================================

# Project root directory
PROJECT_ROOT := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))

# Enable Docker BuildKit for faster builds
export DOCKER_BUILDKIT := 1
export COMPOSE_DOCKER_CLI_BUILD := 1

# ============================================
# Development Environment
# ============================================

.PHONY: build
build: ## Build all images (backend, nginx, worker)
	cd $(PROJECT_ROOT)/deploy && docker-compose build
	docker build -f $(PROJECT_ROOT)/deploy/Dockerfile.worker -t gimr-worker:latest $(PROJECT_ROOT)

.PHONY: up
up: ## Start development environment
	cd $(PROJECT_ROOT)/deploy && docker-compose up -d --build

.PHONY: down
down: ## Stop development environment
	cd $(PROJECT_ROOT)/deploy && docker-compose down

.PHONY: logs
logs: ## View development logs (Ctrl+C to exit)
	cd $(PROJECT_ROOT)/deploy && docker-compose logs -f

.PHONY: ps
ps: ## Show running containers
	cd $(PROJECT_ROOT)/deploy && docker-compose ps

.PHONY: clean
clean: ## Remove containers and volumes
	cd $(PROJECT_ROOT)/deploy && docker-compose down -v --rmi local

.PHONY: restart
restart: down up ## Restart development environment

# ============================================
# Rebuild specific service
# ============================================

.PHONY: rebuild-backend
rebuild-backend: ## Rebuild backend image and restart container
	cd $(PROJECT_ROOT)/deploy && docker-compose build backend
	cd $(PROJECT_ROOT)/deploy && docker-compose up -d backend

.PHONY: rebuild-nginx
rebuild-nginx: ## Rebuild nginx image and restart container
	cd $(PROJECT_ROOT)/deploy && docker-compose build nginx
	cd $(PROJECT_ROOT)/deploy && docker-compose up -d nginx

.PHONY: rebuild-worker
rebuild-worker: ## Rebuild worker image
	docker build -f $(PROJECT_ROOT)/deploy/Dockerfile.worker -t gimr-worker:latest $(PROJECT_ROOT)

# ============================================
# Testing
# ============================================

# --- Unit Tests ---

.PHONY: test
test: test-backend test-frontend test-mock-e2e ## Run all unit tests

.PHONY: test-backend
test-backend: ## Run backend unit tests
	cd $(PROJECT_ROOT)/backend && python -m pytest tests/unit/ -v

.PHONY: test-frontend
test-frontend: ## Run frontend unit tests
	cd $(PROJECT_ROOT)/frontend && npx vitest run

.PHONY: test-mock-e2e
test-mock-e2e: ## Run mock E2E tests
	cd $(PROJECT_ROOT)/backend && python -m pytest tests/mock_e2e/ -v

.PHONY: test-gitlab-e2e
test-gitlab-e2e: ## Run GitLab E2E tests (requires real GitLab)
	cd $(PROJECT_ROOT)/backend && python -m pytest tests/gitlab_e2e/ -v

# --- E2E Tests (requires Docker) ---

.PHONY: test-e2e
test-e2e: e2e-up e2e-test e2e-down ## Full E2E test: up -> test -> down

.PHONY: e2e-up
e2e-up: ## Start E2E test environment
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml up -d --build

.PHONY: e2e-test
e2e-test: ## Run Playwright E2E tests
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml run --rm e2e

.PHONY: e2e-test-specific
e2e-test-specific: ## Run specific E2E test (Usage: make e2e-test-specific TEST_FILE=test_dashboard.py)
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/$(TEST_FILE) -v

.PHONY: e2e-down
e2e-down: ## Stop E2E test environment
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml down

.PHONY: e2e-logs
e2e-logs: ## View E2E test logs
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml logs -f

# --- All Tests ---

.PHONY: test-all
test-all: test test-gitlab-e2e test-e2e ## Run ALL tests

# ============================================
# Help
# ============================================

.PHONY: help
help:
	@echo ""
	@echo "Development Environment:"
	@echo "  make build              Build all images (backend, nginx, worker)"
	@echo "  make up                Start development environment"
	@echo "  make down              Stop development environment"
	@echo "  make restart           Restart development environment"
	@echo "  make logs              View development logs"
	@echo "  make ps                Show running containers"
	@echo "  make clean             Remove containers and volumes"
	@echo ""
	@echo "Rebuild Services:"
	@echo "  make rebuild-backend   Rebuild backend image and restart"
	@echo "  make rebuild-nginx     Rebuild nginx image and restart"
	@echo "  make rebuild-worker   Rebuild worker image"
	@echo ""
	@echo "Unit Tests:"
	@echo "  make test              Run all unit tests"
	@echo "  make test-backend      Run backend unit tests"
	@echo "  make test-frontend     Run frontend unit tests"
	@echo "  make test-mock-e2e     Run mock E2E tests"
	@echo "  make test-gitlab-e2e  Run GitLab E2E tests"
	@echo ""
	@echo "E2E Tests:"
	@echo "  make test-e2e          Full E2E workflow (up -> test -> down)"
	@echo "  make e2e-up           Start E2E environment"
	@echo "  make e2e-test         Run Playwright E2E tests"
	@echo "  make e2e-test-specific  Run specific E2E test"
	@echo "  make e2e-down         Stop E2E environment"
	@echo ""
	@echo "All Tests:"
	@echo "  make test-all          Run ALL tests (unit + gitlab-e2e + playwright-e2e)"
	@echo ""

.DEFAULT_GOAL := help
