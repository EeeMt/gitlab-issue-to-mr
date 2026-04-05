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
	cd $(PROJECT_ROOT)/deploy && docker-compose build --pull=false backend
	cd $(PROJECT_ROOT)/deploy && docker-compose up -d backend

.PHONY: rebuild-scheduler
rebuild-scheduler: ## Rebuild scheduler image and restart container
	cd $(PROJECT_ROOT)/deploy && docker-compose build --pull=false scheduler
	cd $(PROJECT_ROOT)/deploy && docker-compose up -d scheduler

.PHONY: rebuild-nginx
rebuild-nginx: ## Rebuild nginx image and restart container
	cd $(PROJECT_ROOT)/deploy && docker-compose build --pull=false nginx
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

.PHONY: test-unit
test-unit: $(VENV)/.installed $(NODE_MODULES)/.installed ## Run all unit tests with coverage summary
	@_d=$$(mktemp -d); \
	printf "\n\033[1m━━━ Backend unit tests ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"; \
	_t0=$$(date +%s); \
	(cd $(PROJECT_ROOT)/backend && $(VENV_PYTHON) -m pytest tests/unit/ -v --color=yes \
	  --cov=app --cov-report=term-missing:skip-covered; \
	  echo $$? > "$$_d/be.rc") 2>&1 | tee "$$_d/be.log"; \
	echo $$(( $$(date +%s) - $$_t0 )) > "$$_d/be.time"; \
	printf "\n\033[1m━━━ Frontend unit tests ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"; \
	_t0=$$(date +%s); \
	(cd $(PROJECT_ROOT)/frontend && FORCE_COLOR=1 npx vitest run --coverage; \
	  echo $$? > "$$_d/fe.rc") 2>&1 | tee "$$_d/fe.log"; \
	echo $$(( $$(date +%s) - $$_t0 )) > "$$_d/fe.time"; \
	printf "\n\033[1m━━━ Mock E2E tests ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"; \
	_t0=$$(date +%s); \
	(cd $(PROJECT_ROOT)/backend && $(VENV_PYTHON) -m pytest tests/mock_e2e/ -v --color=yes; \
	  echo $$? > "$$_d/me.rc") 2>&1 | tee "$$_d/me.log"; \
	echo $$(( $$(date +%s) - $$_t0 )) > "$$_d/me.time"; \
	r_be=$$(cat "$$_d/be.rc"); r_fe=$$(cat "$$_d/fe.rc"); r_me=$$(cat "$$_d/me.rc"); \
	t_be=$$(cat "$$_d/be.time"); t_fe=$$(cat "$$_d/fe.time"); t_me=$$(cat "$$_d/me.time"); \
	perl -pe 's/\e\[[\d;]*m//g' "$$_d/be.log" > "$$_d/be.c"; \
	perl -pe 's/\e\[[\d;]*m//g' "$$_d/fe.log" > "$$_d/fe.c"; \
	perl -pe 's/\e\[[\d;]*m//g' "$$_d/me.log" > "$$_d/me.c"; \
	be_info=$$(grep -E '^=.*passed' "$$_d/be.c" | tail -1 | sed 's/^[= ]*//;s/[= ]*$$//'); \
	be_cov=$$(grep '^TOTAL' "$$_d/be.c" | awk '{print $$NF}'); \
	[ -z "$$be_cov" ] && be_cov="—"; \
	fe_tests=$$(grep -E 'Tests[[:space:]]+[0-9]' "$$_d/fe.c" | tail -1 | sed 's/^ *//'); \
	fe_dur=$$(grep -E 'Duration[[:space:]]+[0-9]' "$$_d/fe.c" | tail -1 | sed 's/^ *//;s/ (.*//' ); \
	fe_info="$$fe_tests  $$fe_dur"; \
	fe_cov=$$(grep 'All files' "$$_d/fe.c" | head -1 | awk -F'|' '{gsub(/ /,"",$$2); print $$2"%"}'); \
	[ -z "$$fe_cov" ] && fe_cov="—"; \
	me_info=$$(grep -E '^=.*passed' "$$_d/me.c" | tail -1 | sed 's/^[= ]*//;s/[= ]*$$//'); \
	echo ""; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "\033[1m                          Test Suite Summary                             \033[0m\n"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	if [ "$$r_be" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s  \033[1mBackend unit\033[0m   %-42s  \033[36m[%s]\033[0m  %ss\n" "$$_i" "$$be_info" "$$be_cov" "$$t_be"; \
	if [ "$$r_fe" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s  \033[1mFrontend unit\033[0m  %-42s  \033[36m[%s]\033[0m  %ss\n" "$$_i" "$$fe_info" "$$fe_cov" "$$t_fe"; \
	if [ "$$r_me" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s  \033[1mMock E2E\033[0m       %-42s  %ss\n" "$$_i" "$$me_info" "$$t_me"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	_ok=0; [ "$$r_be" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_fe" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_me" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	if [ $$_ok -eq 3 ]; then printf "  ✅  \033[32mALL 3 SUITES PASSED\033[0m\n"; \
	else printf "  ❌  \033[31m$$_ok/3 SUITES PASSED\033[0m\n"; fi; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	rm -rf "$$_d"; \
	[ $$_ok -eq 3 ]

.PHONY: test-backend
test-backend: $(VENV)/.installed ## Run backend unit tests
	cd $(PROJECT_ROOT)/backend && $(VENV_PYTHON) -m pytest tests/unit/ -v

.PHONY: test-frontend
test-frontend: $(NODE_MODULES)/.installed ## Run frontend unit tests
	cd $(PROJECT_ROOT)/frontend && npx vitest run

.PHONY: test-mock-e2e
test-mock-e2e: $(VENV)/.installed ## Run mock E2E tests
	cd $(PROJECT_ROOT)/backend && $(VENV_PYTHON) -m pytest tests/mock_e2e/ -v

.PHONY: test-e2e-gitlab
test-e2e-gitlab: ## Run GitLab E2E tests inside Docker (auto-skips if no GITLAB_BOT_TOKEN)
	$(_E2E_RUN) pytest tests/gitlab_e2e/ -v

.PHONY: test-e2e-ui
test-e2e-ui: ## Run Playwright UI tests only: parallel + serial [RECORD_VIDEO=1 for video]
	$(_E2E_PRE) $(_E2E_RUN) pytest tests/e2e/tests/ -m "not serial" $(_E2E_POST)
	$(_E2E_PRE) $(_E2E_RUN) \
	  pytest tests/e2e/tests/ -m serial \
	  --override-ini="addopts=-v --tb=short --strict-markers --disable-warnings" $(_E2E_POST)

.PHONY: test-e2e
test-e2e: test-e2e-up ## Run ALL E2E tests: UI parallel + UI serial + GitLab [RECORD_VIDEO=1 for video]
	@_d=$$(mktemp -d); \
	printf "\n\033[1m━━━ E2E: Playwright parallel ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"; \
	_t0=$$(date +%s); \
	($(_E2E_PRE) $(_E2E_RUN) pytest tests/e2e/tests/ -m "not serial" $(_E2E_POST); \
	  echo $$? > "$$_d/par.rc") 2>&1 | tee "$$_d/par.log"; \
	echo $$(( $$(date +%s) - $$_t0 )) > "$$_d/par.time"; \
	printf "\n\033[1m━━━ E2E: Playwright serial ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"; \
	_t0=$$(date +%s); \
	($(_E2E_PRE) $(_E2E_RUN) \
	  pytest tests/e2e/tests/ -m serial \
	  --override-ini="addopts=-v --tb=short --strict-markers --disable-warnings" $(_E2E_POST); \
	  echo $$? > "$$_d/ser.rc") 2>&1 | tee "$$_d/ser.log"; \
	echo $$(( $$(date +%s) - $$_t0 )) > "$$_d/ser.time"; \
	printf "\n\033[1m━━━ E2E: GitLab integration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"; \
	_t0=$$(date +%s); \
	($(_E2E_RUN) pytest tests/gitlab_e2e/ -v; \
	  echo $$? > "$$_d/gl.rc") 2>&1 | tee "$$_d/gl.log"; \
	echo $$(( $$(date +%s) - $$_t0 )) > "$$_d/gl.time"; \
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml down; \
	r_par=$$(cat "$$_d/par.rc"); r_ser=$$(cat "$$_d/ser.rc"); r_gl=$$(cat "$$_d/gl.rc"); \
	t_par=$$(cat "$$_d/par.time"); t_ser=$$(cat "$$_d/ser.time"); t_gl=$$(cat "$$_d/gl.time"); \
	perl -pe 's/\e\[[\d;]*m//g' "$$_d/par.log" > "$$_d/par.c"; \
	perl -pe 's/\e\[[\d;]*m//g' "$$_d/ser.log" > "$$_d/ser.c"; \
	perl -pe 's/\e\[[\d;]*m//g' "$$_d/gl.log"  > "$$_d/gl.c"; \
	par_info=$$(grep -E '^=.*(passed|failed)' "$$_d/par.c" | tail -1 | sed 's/^[= ]*//;s/[= ]*$$//'); \
	ser_info=$$(grep -E '^=.*(passed|failed)' "$$_d/ser.c" | tail -1 | sed 's/^[= ]*//;s/[= ]*$$//'); \
	gl_info=$$(grep -E '^=.*(passed|failed|skipped|no tests)' "$$_d/gl.c" | tail -1 | sed 's/^[= ]*//;s/[= ]*$$//'); \
	[ -z "$$gl_info" ] && gl_info="no output (check logs)"; \
	echo ""; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "\033[1m                          E2E Test Summary                               \033[0m\n"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	if [ "$$r_par" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s  \033[1mPlaywright parallel\033[0m  %-40s  %ss\n" "$$_i" "$$par_info" "$$t_par"; \
	if [ "$$r_ser" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s  \033[1mPlaywright serial\033[0m    %-40s  %ss\n" "$$_i" "$$ser_info" "$$t_ser"; \
	if [ "$$r_gl" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s  \033[1mGitLab integration\033[0m   %-40s  %ss\n" "$$_i" "$$gl_info" "$$t_gl"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	_ok=0; [ "$$r_par" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_ser" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_gl" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	if [ $$_ok -eq 3 ]; then printf "  ✅  \033[32mALL 3 E2E SUITES PASSED\033[0m\n"; \
	else printf "  ❌  \033[31m$$_ok/3 E2E SUITES PASSED\033[0m\n"; fi; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	rm -rf "$$_d"; \
	[ $$_ok -eq 3 ]

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
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml up -d --build --wait postgres backend nginx scheduler

.PHONY: test-e2e-down
test-e2e-down: ## Stop E2E test environment
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml down

.PHONY: test-e2e-logs
test-e2e-logs: ## View E2E test logs
	cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml logs -f

.PHONY: test-all
test-all: $(VENV)/.installed $(NODE_MODULES)/.installed ## Run ALL tests: unit + E2E (with overall summary)
	@r_unit=0; r_e2e=0; \
	_t0=$$(date +%s); \
	$(MAKE) --no-print-directory test-unit || r_unit=1; \
	t_unit=$$(( $$(date +%s) - $$_t0 )); \
	_t0=$$(date +%s); \
	$(MAKE) --no-print-directory test-e2e  || r_e2e=1; \
	t_e2e=$$(( $$(date +%s) - $$_t0 )); \
	t_total=$$(( $$t_unit + $$t_e2e )); \
	echo ""; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "\033[1m                         Full Test Suite Summary                         \033[0m\n"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	if [ "$$r_unit" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s  \033[1mUnit tests\033[0m   (backend + frontend + mock-e2e)  %ss\n" "$$_i" "$$t_unit"; \
	if [ "$$r_e2e" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s  \033[1mE2E tests\033[0m    (playwright + gitlab)            %ss\n" "$$_i" "$$t_e2e"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	_ok=0; [ "$$r_unit" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_e2e" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	if [ $$_ok -eq 2 ]; then printf "  ✅  \033[32mALL PASSED\033[0m  (total %ss)\n" "$$t_total"; \
	else printf "  ❌  \033[31m$$_ok/2 GROUPS PASSED\033[0m  (total %ss)\n" "$$t_total"; fi; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	[ $$_ok -eq 2 ]

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
	@echo "  make rebuild-scheduler Rebuild scheduler image and restart"
	@echo "  make rebuild-nginx    Rebuild nginx image and restart"
	@echo "  make rebuild-worker   Rebuild worker image"
	@echo ""
	@echo "Unit Tests:"
	@echo "  make test-unit         Run all unit tests (backend + frontend + mock-e2e) with coverage"
	@echo "  make test-backend      Run backend unit tests"
	@echo "  make test-frontend     Run frontend unit tests"
	@echo "  make test-mock-e2e     Run mock E2E tests"
	@echo ""
	@echo "E2E Tests:"
	@echo "  make test-e2e                        Run ALL E2E: parallel + serial + gitlab + cleanup"
	@echo "  make test-e2e RECORD_VIDEO=1               Run ALL E2E with video recording"
	@echo "  make test-e2e-ui                     Run Playwright UI tests only (parallel + serial)"
	@echo "  make test-e2e-gitlab                 Run GitLab integration tests only"
	@echo "  make test-e2e-parallel               Run parallel Playwright tests only (~44s)"
	@echo "  make test-e2e-serial                 Run serial Playwright tests only (~42s)"
	@echo "  make test-e2e-specific TEST_FILE=..  Run specific test file"
	@echo "  make test-e2e-up                     Start E2E environment"
	@echo "  make test-e2e-down                   Stop E2E environment"
	@echo "  make test-e2e-logs                   View E2E logs"
	@echo "  Videos saved to deploy/e2e-videos/ (RECORD_VIDEO=1 only)"
	@echo ""
	@echo "All Tests:"
	@echo "  make test-all          Run ALL tests (unit + E2E) with overall summary"
	@echo ""

.DEFAULT_GOAL := help
