# Makefile for Codify
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
	docker build -f $(PROJECT_ROOT)/deploy/Dockerfile.worker -t codify-worker:latest $(PROJECT_ROOT)

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
# Rebuild Services
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
	docker build -f $(PROJECT_ROOT)/deploy/Dockerfile.worker -t codify-worker:latest $(PROJECT_ROOT)

# ============================================
# Testing
# ============================================

# Backend virtual environment
VENV      := $(PROJECT_ROOT)/backend/.venv
VENV_PYTHON := $(VENV)/bin/python

# Sentinel file: recreated whenever requirements change
$(VENV)/.installed: $(PROJECT_ROOT)/backend/requirements.txt $(PROJECT_ROOT)/backend/requirements-test.txt
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r $(PROJECT_ROOT)/backend/requirements.txt -q
	$(VENV)/bin/pip install -r $(PROJECT_ROOT)/backend/requirements-test.txt -q
	touch $(VENV)/.installed

.PHONY: setup-venv
setup-venv: $(VENV)/.installed ## Create/update backend virtualenv

# Frontend node_modules
NODE_MODULES := $(PROJECT_ROOT)/frontend/node_modules

# Sentinel file: recreated whenever package.json or package-lock.json change
$(NODE_MODULES)/.installed: $(PROJECT_ROOT)/frontend/package.json $(PROJECT_ROOT)/frontend/package-lock.json
	cd $(PROJECT_ROOT)/frontend && npm install --prefer-offline --no-audit --no-fund
	touch $(NODE_MODULES)/.installed

.PHONY: setup-npm
setup-npm: $(NODE_MODULES)/.installed ## Install frontend npm dependencies

.PHONY: setup
setup: setup-venv setup-npm ## Install all dependencies (backend venv + frontend npm)

# Video recording option: set RECORD_VIDEO=1 to record .webm videos for each test
# Example: make test-e2e-parallel RECORD_VIDEO=1
RECORD_VIDEO ?= 0

ifeq ($(RECORD_VIDEO),1)
_E2E_PRE  = docker rm -f codify-e2e-recorder 2>/dev/null || true && mkdir -p $(PROJECT_ROOT)/deploy/e2e-videos &&
_E2E_RUN  = cd $(PROJECT_ROOT)/deploy && E2E_RECORD_VIDEO=1 docker-compose -f docker-compose.e2e.yml run --name codify-e2e-recorder e2e
_E2E_POST = ; E2E_EXIT=$$?; docker cp codify-e2e-recorder:/videos/. $(PROJECT_ROOT)/deploy/e2e-videos/ 2>/dev/null || true; docker rm -f codify-e2e-recorder 2>/dev/null || true; echo "Videos → deploy/e2e-videos/"; exit $$E2E_EXIT
else
_E2E_PRE  =
_E2E_RUN  = cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml run --rm e2e
_E2E_POST =
endif

.PHONY: test
test: test-backend test-frontend test-mock-e2e ## Run all unit tests

.PHONY: test-backend
test-backend: $(VENV)/.installed ## Run backend unit tests
	cd $(PROJECT_ROOT)/backend && $(VENV_PYTHON) -m pytest tests/unit/ -v

.PHONY: test-frontend
test-frontend: $(NODE_MODULES)/.installed ## Run frontend unit tests
	cd $(PROJECT_ROOT)/frontend && npx vitest run

.PHONY: test-mock-e2e
test-mock-e2e: $(VENV)/.installed ## Run mock E2E tests
	cd $(PROJECT_ROOT)/backend && $(VENV_PYTHON) -m pytest tests/mock_e2e/ -v

.PHONY: test-gitlab-e2e
test-gitlab-e2e: $(VENV)/.installed ## Run GitLab E2E tests (requires real GitLab)
	cd $(PROJECT_ROOT)/backend && $(VENV_PYTHON) -m pytest tests/gitlab_e2e/ -v

.PHONY: test-e2e
test-e2e: test-e2e-up ## Run ALL Playwright E2E tests: parallel + serial [RECORD_VIDEO=1 for video]
	$(_E2E_PRE) $(_E2E_RUN) pytest tests/e2e/tests/ -m "not serial" $(_E2E_POST)
	$(_E2E_PRE) $(_E2E_RUN) \
	  pytest tests/e2e/tests/ -m serial \
	  --override-ini="addopts=-v --tb=short --strict-markers --disable-warnings" $(_E2E_POST)
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml down

.PHONY: test-e2e-parallel
test-e2e-parallel: ## Run parallel E2E tests only (116 tests, ~44s) [RECORD_VIDEO=1 for video]
	$(_E2E_PRE) $(_E2E_RUN) pytest tests/e2e/tests/ -m "not serial" $(_E2E_POST)

.PHONY: test-e2e-serial
test-e2e-serial: ## Run serial E2E tests only: bootstrap/prompt_template/access_management (~42s) [RECORD_VIDEO=1]
	$(_E2E_PRE) $(_E2E_RUN) \
	  pytest tests/e2e/tests/ -m serial \
	  --override-ini="addopts=-v --tb=short --strict-markers --disable-warnings" $(_E2E_POST)

.PHONY: test-e2e-specific
test-e2e-specific: ## Run specific E2E test file [TEST_FILE=test_dashboard.py] [RECORD_VIDEO=1]
	$(_E2E_PRE) $(_E2E_RUN) pytest tests/e2e/tests/$(TEST_FILE) -v $(_E2E_POST)

.PHONY: test-e2e-up
test-e2e-up: ## Start E2E test environment (builds images if changed)
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml up -d --build --wait postgres backend nginx

.PHONY: test-e2e-down
test-e2e-down: ## Stop E2E test environment
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml down

.PHONY: test-e2e-logs
test-e2e-logs: ## View E2E test logs
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml logs -f

.PHONY: test-all
test-all: test test-gitlab-e2e test-e2e ## Run ALL tests (unit + gitlab-e2e + playwright-e2e)

# ============================================
# Help
# ============================================

.PHONY: help
help:
	@echo ""
	@echo "Setup (run once after fresh checkout):"
	@echo "  make setup             Install all dependencies (backend venv + frontend npm)"
	@echo "  make setup-venv        Create/update backend Python virtualenv"
	@echo "  make setup-npm         Install frontend npm dependencies"
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
	@echo "  make rebuild-nginx    Rebuild nginx image and restart"
	@echo "  make rebuild-worker   Rebuild worker image"
	@echo ""
	@echo "Unit Tests:"
	@echo "  make test              Run all unit tests"
	@echo "  make test-backend      Run backend unit tests"
	@echo "  make test-frontend     Run frontend unit tests"
	@echo "  make test-mock-e2e     Run mock E2E tests"
	@echo "  make test-gitlab-e2e  Run GitLab E2E tests"
	@echo ""
	@echo "Playwright E2E Tests:"
	@echo "  make test-e2e                        Run ALL E2E tests (parallel + serial + down)"
	@echo "  make test-e2e RECORD_VIDEO=1               Run ALL E2E tests with video recording"
	@echo "  make test-e2e-parallel               Run parallel tests only (116 tests, ~44s)"
	@echo "  make test-e2e-parallel RECORD_VIDEO=1      Run parallel tests with video recording"
	@echo "  make test-e2e-serial                 Run serial tests only (18 tests, ~42s)"
	@echo "  make test-e2e-serial RECORD_VIDEO=1        Run serial tests with video recording"
	@echo "  make test-e2e-specific TEST_FILE=..  Run specific test file"
	@echo "  make test-e2e-up                     Start E2E environment"
	@echo "  make test-e2e-down                   Stop E2E environment"
	@echo "  make test-e2e-logs                   View E2E logs"
	@echo "  Videos are saved to deploy/e2e-videos/ (RECORD_VIDEO=1 only)"
	@echo ""
	@echo "All Tests:"
	@echo "  make test-all          Run ALL tests (unit + gitlab-e2e + playwright-e2e)"
	@echo ""

.DEFAULT_GOAL := help
