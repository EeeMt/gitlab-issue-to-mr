# Makefile for Codify
# ============================================

# Project root directory
PROJECT_ROOT := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
GIT_COMMIT ?= $(shell git -C $(PROJECT_ROOT) rev-parse HEAD 2>/dev/null || printf unknown)
export GIT_COMMIT

# Enable Docker BuildKit for faster builds
export DOCKER_BUILDKIT := 1
export COMPOSE_DOCKER_CLI_BUILD := 1
WORKER_KIT_VERSION ?= 0.3.0
WORKER_KIT_PLATFORM ?= linux/amd64
JAVA21_MAVEN_WORKER_DOCKERFILE := $(PROJECT_ROOT)/deploy/Dockerfile.worker-java21-maven

# ============================================
# Development Environment
# ============================================

.PHONY: build
build: ## Build all images (backend, nginx, worker)
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test build
	docker build -f $(JAVA21_MAVEN_WORKER_DOCKERFILE) -t codify-worker/java21-maven:2026.07 $(PROJECT_ROOT)
	@printf "\nBuild summary:\n"
	@printf "  - codify-backend:latest\n"
	@printf "  - codify-nginx:latest\n"
	@printf "  - codify-worker/java21-maven:2026.07\n"

.PHONY: offline-bundle-export
offline-bundle-export: ## Build images, export offline bundle images, and package deploy/offline-bundle
	$(MAKE) build
	WORKER_KIT_VERSION=$(WORKER_KIT_VERSION) WORKER_KIT_PLATFORM=linux/amd64 $(PROJECT_ROOT)/deploy/worker-kit/export.sh
	WORKER_KIT_VERSION=$(WORKER_KIT_VERSION) WORKER_KIT_PLATFORM=linux/arm64 $(PROJECT_ROOT)/deploy/worker-kit/export.sh
	cd $(PROJECT_ROOT)/deploy/offline-bundle && ./scripts/export-images.sh
	cd $(PROJECT_ROOT)/deploy/offline-bundle && ./scripts/package-bundle.sh

.PHONY: worker-kit-export
worker-kit-export: ## Build and export the portable mounted worker kit
	WORKER_KIT_VERSION=$(WORKER_KIT_VERSION) WORKER_KIT_PLATFORM=$(WORKER_KIT_PLATFORM) $(PROJECT_ROOT)/deploy/worker-kit/export.sh

.PHONY: worker-kit-verify
worker-kit-verify: ## Verify KIT_PATH against RUNTIME_IMAGE (optional CLAUDE_HOST_PATH and SMOKE)
	$(PROJECT_ROOT)/deploy/worker-kit/verify-runtime.sh --kit "$(KIT_PATH)" --image "$(RUNTIME_IMAGE)" $(if $(CLAUDE_HOST_PATH),--claude-host-path "$(CLAUDE_HOST_PATH)") $(if $(CLAUDE_CONTAINER_PATH),--claude-container-path "$(CLAUDE_CONTAINER_PATH)") $(if $(SMOKE),--smoke "$(SMOKE)")

.PHONY: up
up: ## Start development environment (rebuilds backend, nginx, and worker images)
	docker build -f $(JAVA21_MAVEN_WORKER_DOCKERFILE) -t codify-worker/java21-maven:2026.07 $(PROJECT_ROOT)
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test up -d --build

.PHONY: down
down: ## Stop development environment
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test down

.PHONY: logs
logs: ## View development logs (Ctrl+C to exit)
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test logs -f

.PHONY: ps
ps: ## Show running containers
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test ps

.PHONY: clean
clean: ## Remove containers and volumes
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test down -v --rmi local

.PHONY: restart
restart: down up ## Restart development environment

# ============================================
# Rebuild Services
# ============================================

.PHONY: rebuild-backend
rebuild-backend: ## Rebuild backend image and restart container
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test build --pull=false backend
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test up -d backend

.PHONY: rebuild-scheduler
rebuild-scheduler: ## Rebuild scheduler image and restart container
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test build --pull=false scheduler
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test up -d scheduler

.PHONY: rebuild-nginx
rebuild-nginx: ## Rebuild nginx image and restart container
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test build --pull=false nginx
	cd $(PROJECT_ROOT)/deploy && docker-compose --env-file .env.test up -d nginx

.PHONY: rebuild-worker
rebuild-worker: ## Rebuild worker image
	docker build -f $(JAVA21_MAVEN_WORKER_DOCKERFILE) -t codify-worker/java21-maven:2026.07 $(PROJECT_ROOT)

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

.PHONY: lint-backend
lint-backend: $(VENV)/.installed ## Run backend Ruff checks
	cd $(PROJECT_ROOT)/backend && $(VENV_PYTHON) -m ruff check app tests

.PHONY: lint
lint: lint-backend ## Run all lint checks

# Video recording option: set RECORD_VIDEO=1 to record .webm videos for each test
# Example: make test-e2e-parallel RECORD_VIDEO=1
RECORD_VIDEO ?= 0

ifeq ($(RECORD_VIDEO),1)
_E2E_PRE  = docker rm -f codify-e2e-recorder 2>/dev/null || true && mkdir -p $(PROJECT_ROOT)/deploy/e2e-videos &&
_E2E_RUN  = cd $(PROJECT_ROOT)/deploy && E2E_RECORD_VIDEO=1 docker-compose -f docker-compose.e2e.yml run --name codify-e2e-recorder -e FORCE_COLOR=1 -e PY_COLORS=1 e2e
_E2E_POST = ; E2E_EXIT=$$?; docker cp codify-e2e-recorder:/videos/. $(PROJECT_ROOT)/deploy/e2e-videos/ 2>/dev/null || true; docker rm -f codify-e2e-recorder 2>/dev/null || true; echo "Videos → deploy/e2e-videos/"; exit $$E2E_EXIT
else
_E2E_PRE  =
_E2E_RUN  = cd $(PROJECT_ROOT)/deploy && docker-compose -f docker-compose.e2e.yml run --rm -e FORCE_COLOR=1 -e PY_COLORS=1 e2e
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
	(cd $(PROJECT_ROOT)/frontend && \
	  if [ "$$(uname)" = "Darwin" ]; then \
	    script -q /dev/null bash -c 'FORCE_COLOR=1 npx vitest run --coverage'; \
	  else \
	    script -qec 'FORCE_COLOR=1 npx vitest run --coverage' /dev/null; \
	  fi; \
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
	_bl=$$(grep -E '^=.*(passed|failed)' "$$_d/be.c" | tail -1); \
	be_p=$$(echo "$$_bl" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+'); \
	be_f=$$(echo "$$_bl" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+'); \
	be_s=$$(echo "$$_bl" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+'); \
	[ -z "$$be_p" ] && be_p=0; [ -z "$$be_f" ] && be_f=0; [ -z "$$be_s" ] && be_s=0; \
	be_cov=$$(grep '^TOTAL' "$$_d/be.c" | awk '{print $$NF}'); \
	[ -z "$$be_cov" ] && be_cov="—"; \
	_fl=$$(grep -E 'Tests.*passed' "$$_d/fe.c" | tail -1); \
	fe_p=$$(echo "$$_fl" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+'); \
	fe_f=$$(echo "$$_fl" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+'); \
	[ -z "$$fe_p" ] && fe_p=0; [ -z "$$fe_f" ] && fe_f=0; fe_s=0; \
	fe_cov=$$(grep 'All files' "$$_d/fe.c" | head -1 | awk -F'|' '{gsub(/ /,"",$$2); print $$2"%"}'); \
	[ -z "$$fe_cov" ] && fe_cov="—"; \
	_ml=$$(grep -E '^=.*(passed|failed)' "$$_d/me.c" | tail -1); \
	me_p=$$(echo "$$_ml" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+'); \
	me_f=$$(echo "$$_ml" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+'); \
	me_s=$$(echo "$$_ml" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+'); \
	[ -z "$$me_p" ] && me_p=0; [ -z "$$me_f" ] && me_f=0; [ -z "$$me_s" ] && me_s=0; \
	tot_p=$$(( $$be_p + $$fe_p + $$me_p )); \
	tot_f=$$(( $$be_f + $$fe_f + $$me_f )); \
	tot_s=$$(( $$be_s + $$fe_s + $$me_s )); \
	tot_t=$$(( $$t_be + $$t_fe + $$t_me )); \
	echo ""; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "\033[1m                          Unit Test Summary                              \033[0m\n"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "  \033[1m%-18s %6s  %6s  %7s  %8s  %5s\033[0m\n" "Suite" "Passed" "Failed" "Skipped" "Coverage" "Time"; \
	printf "  %-18s %6s  %6s  %7s  %8s  %5s\n" "──────────────────" "──────" "──────" "───────" "────────" "─────"; \
	if [ "$$r_be" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s %-16s %6s  %6s  %7s  \033[36m%8s\033[0m  %4ss\n" "$$_i" "Backend" "$$be_p" "$$be_f" "$$be_s" "$$be_cov" "$$t_be"; \
	if [ "$$r_fe" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s %-16s %6s  %6s  %7s  \033[36m%8s\033[0m  %4ss\n" "$$_i" "Frontend" "$$fe_p" "$$fe_f" "$$fe_s" "$$fe_cov" "$$t_fe"; \
	if [ "$$r_me" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s %-16s %6s  %6s  %7s  %8s  %4ss\n" "$$_i" "Mock E2E" "$$me_p" "$$me_f" "$$me_s" "—" "$$t_me"; \
	printf "  %-18s %6s  %6s  %7s  %8s  %5s\n" "──────────────────" "──────" "──────" "───────" "────────" "─────"; \
	printf "  \033[1m%-18s %6s  %6s  %7s  %8s  %4ss\033[0m\n" "Total" "$$tot_p" "$$tot_f" "$$tot_s" "" "$$tot_t"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	_ok=0; [ "$$r_be" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_fe" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_me" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	if [ $$_ok -eq 3 ]; then printf "  ✅  \033[32mALL 3 SUITES PASSED\033[0m\n"; \
	else printf "  ❌  \033[31m$$_ok/3 SUITES PASSED\033[0m\n"; fi; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	if [ -n "$${_RESULTS_FILE}" ]; then \
	  echo "Backend:$$be_p:$$be_f:$$be_s:$$be_cov:$$t_be:$$r_be" >> "$${_RESULTS_FILE}"; \
	  echo "Frontend:$$fe_p:$$fe_f:$$fe_s:$$fe_cov:$$t_fe:$$r_fe" >> "$${_RESULTS_FILE}"; \
	  echo "Mock E2E:$$me_p:$$me_f:$$me_s:—:$$t_me:$$r_me" >> "$${_RESULTS_FILE}"; \
	fi; \
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

# ---------------------------------------------------------------------------
# Mock Integration Tests (full lifecycle with mock GitLab + fake Claude)
# ---------------------------------------------------------------------------

MOCK_INT_COMPOSE := $(PROJECT_ROOT)/backend/tests/mock_integration/docker-compose.mock-test.yml
MOCK_STACK_SCRIPT := $(PROJECT_ROOT)/scripts/run-mock-stack.sh

# Common flags for run-mock-stack.sh
_MOCK_COMMON := -c $(MOCK_INT_COMPOSE) -s $(PROJECT_ROOT)

.PHONY: test-mock-integration-build
test-mock-integration-build: ## Build images for mock integration tests
	docker build -f $(PROJECT_ROOT)/deploy/Dockerfile.backend -t codify-backend:latest $(PROJECT_ROOT)
	docker build -f $(PROJECT_ROOT)/backend/tests/mock_integration/Dockerfile.backend-test -t codify-backend-test:latest $(PROJECT_ROOT)
	docker build -f $(PROJECT_ROOT)/backend/tests/mock_integration/mock_server/Dockerfile -t codify-mock-services:latest $(PROJECT_ROOT)
	docker build -f $(PROJECT_ROOT)/backend/tests/mock_integration/fake_claude/Dockerfile.worker-test -t codify-worker-test:latest $(PROJECT_ROOT)
	@echo "Mock integration test images built: codify-backend:latest, codify-backend-test:latest, codify-mock-services:latest, codify-worker-test:latest"

.PHONY: test-mock-integration-up
test-mock-integration-up: test-mock-integration-build ## Start mock integration test environment
	docker-compose -f $(MOCK_INT_COMPOSE) up -d --wait postgres mock-services backend scheduler

.PHONY: test-mock-integration-down
test-mock-integration-down: ## Stop mock integration test environment
	docker-compose -f $(MOCK_INT_COMPOSE) down -v

.PHONY: test-mock-integration-logs
test-mock-integration-logs: ## View mock integration test logs
	docker-compose -f $(MOCK_INT_COMPOSE) logs -f

.PHONY: test-mock-integration
test-mock-integration: test-mock-integration-build ## Run mock integration tests (sequential, single stack)
	$(MOCK_STACK_SCRIPT) $(_MOCK_COMMON) -d || \
		{ docker-compose -f $(MOCK_INT_COMPOSE) logs; false; }

# --- Three-stack parallel mock integration tests ---
# Test file counts: remaining_endpoints(25), health_access_sse(25), notifications_and_operations(17),
# mutex_and_scheduling(15), system_apis(14), admin_and_templates(13), validation_and_dedup(12),
# security_and_resilience(12), entrypoint_paths(12), edge_cases_advanced(12), api_endpoints(12),
# mr_followup_and_env(11), entrypoint(11), failure_injection(10), webhook_and_lifecycle(7),
# gap_analysis(7), edge_cases(7), advanced(6), happy_path(4), coverage_gaps(4), additional(4),
# failure_paths(3), scheduling(2)

# Group A: 82 tests
MOCK_GROUP_A := test_remaining_endpoints.py test_entrypoint_paths.py \
	test_api_endpoints.py test_failure_injection.py test_happy_path.py \
	test_additional.py test_coverage_gaps.py test_failure_paths.py \
	test_scheduling.py
# Group B: 82 tests
MOCK_GROUP_B := test_health_access_sse.py test_mutex_and_scheduling.py \
	test_system_apis.py test_edge_cases.py test_webhook_and_lifecycle.py \
	test_gap_analysis.py test_advanced.py
# Group C: 81 tests
MOCK_GROUP_C := test_notifications_and_operations.py test_admin_and_templates.py \
	test_validation_and_dedup.py test_security_and_resilience.py \
	test_edge_cases_advanced.py test_mr_followup_and_env.py \
	test_entrypoint.py

.PHONY: test-mock-integration-parallel
test-mock-integration-parallel: test-mock-integration-build ## Run mock integration tests in parallel (three stacks)
	@_d=$$(mktemp -d); _t0=$$(date +%s); \
	printf "\n\033[1;33m━━━ Parallel Mock Integration Tests (3 stacks) ━━━\033[0m\n\n"; \
	( $(MOCK_STACK_SCRIPT) $(_MOCK_COMMON) -d \
		-p mock_a -n codify-mock-test-a -w mocka -P 19000 -B 18000 -l A \
		$(MOCK_GROUP_A); \
	  echo $$? > "$$_d/a.rc" \
	) 2>&1 | sed 's/^/[A] /' & \
	( $(MOCK_STACK_SCRIPT) $(_MOCK_COMMON) -d \
		-p mock_b -n codify-mock-test-b -w mockb -P 19001 -B 18001 -l B \
		$(MOCK_GROUP_B); \
	  echo $$? > "$$_d/b.rc" \
	) 2>&1 | sed 's/^/[B] /' & \
	( $(MOCK_STACK_SCRIPT) $(_MOCK_COMMON) -d \
		-p mock_c -n codify-mock-test-c -w mockc -P 19002 -B 18002 -l C \
		$(MOCK_GROUP_C); \
	  echo $$? > "$$_d/c.rc" \
	) 2>&1 | sed 's/^/[C] /' & \
	wait; \
	_elapsed=$$(( $$(date +%s) - $$_t0 )); \
	_ra=$$(cat "$$_d/a.rc" 2>/dev/null || echo 1); \
	_rb=$$(cat "$$_d/b.rc" 2>/dev/null || echo 1); \
	_rc=$$(cat "$$_d/c.rc" 2>/dev/null || echo 1); \
	printf "\n\033[1;33m━━━ Results ━━━\033[0m\n"; \
	if [ "$$_ra" = "0" ]; then _sa="PASS"; else _sa="FAIL"; fi; \
	if [ "$$_rb" = "0" ]; then _sb="PASS"; else _sb="FAIL"; fi; \
	if [ "$$_rc" = "0" ]; then _sc="PASS"; else _sc="FAIL"; fi; \
	printf "Stack A: %s   Stack B: %s   Stack C: %s   Time: %ds\n" "$$_sa" "$$_sb" "$$_sc" "$$_elapsed"; \
	rm -rf "$$_d"; \
	[ "$$_ra" = "0" ] && [ "$$_rb" = "0" ] && [ "$$_rc" = "0" ]

.PHONY: test-e2e-gitlab
test-e2e-gitlab: ## Run GitLab E2E tests inside Docker (auto-skips if no GITLAB_BOT_TOKEN)
	$(_E2E_RUN) pytest tests/gitlab_e2e/ -v

.PHONY: test-e2e-ui
test-e2e-ui: ## Run Playwright UI tests only: parallel + serial [RECORD_VIDEO=1 for video]
	@_d=$$(mktemp -d); \
	printf "\n\033[1m━━━ UI E2E: parallel ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"; \
	_t0=$$(date +%s); \
	($(_E2E_PRE) $(_E2E_RUN) pytest tests/e2e/tests/ -m "not serial" $(_E2E_POST); \
	  echo $$? > "$$_d/par.rc") 2>&1 | tee "$$_d/par.log"; \
	echo $$(( $$(date +%s) - $$_t0 )) > "$$_d/par.time"; \
	printf "\n\033[1m━━━ UI E2E: serial ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"; \
	_t0=$$(date +%s); \
	($(_E2E_PRE) $(_E2E_RUN) \
	  pytest tests/e2e/tests/ -m serial \
	  --override-ini="addopts=-v --tb=short --strict-markers --disable-warnings" $(_E2E_POST); \
	  echo $$? > "$$_d/ser.rc") 2>&1 | sed 's/[0-9]* deselected, //g; s/, [0-9]* deselected//g' | tee "$$_d/ser.log"; \
	echo $$(( $$(date +%s) - $$_t0 )) > "$$_d/ser.time"; \
	r_par=$$(cat "$$_d/par.rc"); r_ser=$$(cat "$$_d/ser.rc"); \
	t_par=$$(cat "$$_d/par.time"); t_ser=$$(cat "$$_d/ser.time"); \
	perl -pe 's/\e\[[\d;]*m//g' "$$_d/par.log" > "$$_d/par.c"; \
	perl -pe 's/\e\[[\d;]*m//g' "$$_d/ser.log" > "$$_d/ser.c"; \
	_pl=$$(grep -E '^=.*(passed|failed)' "$$_d/par.c" | tail -1); \
	par_p=$$(echo "$$_pl" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+'); \
	par_f=$$(echo "$$_pl" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+'); \
	par_s=$$(echo "$$_pl" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+'); \
	[ -z "$$par_p" ] && par_p=0; [ -z "$$par_f" ] && par_f=0; [ -z "$$par_s" ] && par_s=0; \
	_sl=$$(grep -E '^=.*(passed|failed)' "$$_d/ser.c" | tail -1); \
	ser_p=$$(echo "$$_sl" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+'); \
	ser_f=$$(echo "$$_sl" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+'); \
	ser_s=$$(echo "$$_sl" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+'); \
	[ -z "$$ser_p" ] && ser_p=0; [ -z "$$ser_f" ] && ser_f=0; [ -z "$$ser_s" ] && ser_s=0; \
	tot_p=$$(( $$par_p + $$ser_p )); \
	tot_f=$$(( $$par_f + $$ser_f )); \
	tot_s=$$(( $$par_s + $$ser_s )); \
	tot_t=$$(( $$t_par + $$t_ser )); \
	echo ""; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "\033[1m                       UI E2E Test Summary                               \033[0m\n"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "  \033[1m%-20s %6s  %6s  %7s  %5s\033[0m\n" "Suite" "Passed" "Failed" "Skipped" "Time"; \
	printf "  %-20s %6s  %6s  %7s  %5s\n" "────────────────────" "──────" "──────" "───────" "─────"; \
	if [ "$$r_par" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s %-18s %6s  %6s  %7s  %4ss\n" "$$_i" "Parallel" "$$par_p" "$$par_f" "$$par_s" "$$t_par"; \
	if [ "$$r_ser" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s %-18s %6s  %6s  %7s  %4ss\n" "$$_i" "Serial" "$$ser_p" "$$ser_f" "$$ser_s" "$$t_ser"; \
	printf "  %-20s %6s  %6s  %7s  %5s\n" "────────────────────" "──────" "──────" "───────" "─────"; \
	printf "  \033[1m%-20s %6s  %6s  %7s  %4ss\033[0m\n" "Total" "$$tot_p" "$$tot_f" "$$tot_s" "$$tot_t"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	_ok=0; [ "$$r_par" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_ser" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	if [ $$_ok -eq 2 ]; then printf "  ✅  \033[32mALL 2 UI E2E SUITES PASSED\033[0m\n"; \
	else printf "  ❌  \033[31m$$_ok/2 UI E2E SUITES PASSED\033[0m\n"; fi; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	rm -rf "$$_d"; \
	[ $$_ok -eq 2 ]

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
	  echo $$? > "$$_d/ser.rc") 2>&1 | sed 's/[0-9]* deselected, //g; s/, [0-9]* deselected//g' | tee "$$_d/ser.log"; \
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
	_pl=$$(grep -E '^=.*(passed|failed)' "$$_d/par.c" | tail -1); \
	par_p=$$(echo "$$_pl" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+'); \
	par_f=$$(echo "$$_pl" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+'); \
	par_s=$$(echo "$$_pl" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+'); \
	[ -z "$$par_p" ] && par_p=0; [ -z "$$par_f" ] && par_f=0; [ -z "$$par_s" ] && par_s=0; \
	_sl=$$(grep -E '^=.*(passed|failed)' "$$_d/ser.c" | tail -1); \
	ser_p=$$(echo "$$_sl" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+'); \
	ser_f=$$(echo "$$_sl" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+'); \
	ser_s=$$(echo "$$_sl" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+'); \
	[ -z "$$ser_p" ] && ser_p=0; [ -z "$$ser_f" ] && ser_f=0; [ -z "$$ser_s" ] && ser_s=0; \
	_gll=$$(grep -E '^=.*(passed|failed|skipped|no tests)' "$$_d/gl.c" | tail -1); \
	gl_p=$$(echo "$$_gll" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+'); \
	gl_f=$$(echo "$$_gll" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+'); \
	gl_s=$$(echo "$$_gll" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+'); \
	[ -z "$$gl_p" ] && gl_p=0; [ -z "$$gl_f" ] && gl_f=0; [ -z "$$gl_s" ] && gl_s=0; \
	tot_p=$$(( $$par_p + $$ser_p + $$gl_p )); \
	tot_f=$$(( $$par_f + $$ser_f + $$gl_f )); \
	tot_s=$$(( $$par_s + $$ser_s + $$gl_s )); \
	tot_t=$$(( $$t_par + $$t_ser + $$t_gl )); \
	echo ""; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "\033[1m                          E2E Test Summary                               \033[0m\n"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "  \033[1m%-20s %6s  %6s  %7s  %5s\033[0m\n" "Suite" "Passed" "Failed" "Skipped" "Time"; \
	printf "  %-20s %6s  %6s  %7s  %5s\n" "────────────────────" "──────" "──────" "───────" "─────"; \
	if [ "$$r_par" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s %-18s %6s  %6s  %7s  %4ss\n" "$$_i" "UI parallel" "$$par_p" "$$par_f" "$$par_s" "$$t_par"; \
	if [ "$$r_ser" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s %-18s %6s  %6s  %7s  %4ss\n" "$$_i" "UI serial" "$$ser_p" "$$ser_f" "$$ser_s" "$$t_ser"; \
	if [ "$$r_gl" = "0" ]; then _i="✅"; else _i="❌"; fi; \
	printf "  %s %-18s %6s  %6s  %7s  %4ss\n" "$$_i" "GitLab E2E" "$$gl_p" "$$gl_f" "$$gl_s" "$$t_gl"; \
	printf "  %-20s %6s  %6s  %7s  %5s\n" "────────────────────" "──────" "──────" "───────" "─────"; \
	printf "  \033[1m%-20s %6s  %6s  %7s  %4ss\033[0m\n" "Total" "$$tot_p" "$$tot_f" "$$tot_s" "$$tot_t"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	_ok=0; [ "$$r_par" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_ser" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	[ "$$r_gl" = "0" ] && _ok=$$(( $$_ok + 1 )); \
	if [ $$_ok -eq 3 ]; then printf "  ✅  \033[32mALL 3 E2E SUITES PASSED\033[0m\n"; \
	else printf "  ❌  \033[31m$$_ok/3 E2E SUITES PASSED\033[0m\n"; fi; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	if [ -n "$${_RESULTS_FILE}" ]; then \
	  echo "UI parallel:$$par_p:$$par_f:$$par_s:—:$$t_par:$$r_par" >> "$${_RESULTS_FILE}"; \
	  echo "UI serial:$$ser_p:$$ser_f:$$ser_s:—:$$t_ser:$$r_ser" >> "$${_RESULTS_FILE}"; \
	  echo "GitLab E2E:$$gl_p:$$gl_f:$$gl_s:—:$$t_gl:$$r_gl" >> "$${_RESULTS_FILE}"; \
	fi; \
	rm -rf "$$_d"; \
	[ $$_ok -eq 3 ]

.PHONY: test-e2e-parallel
test-e2e-parallel: ## Run parallel E2E tests only (116 tests, ~44s) [RECORD_VIDEO=1 for video]
	$(_E2E_PRE) $(_E2E_RUN) pytest tests/e2e/tests/ -m "not serial" $(_E2E_POST)

.PHONY: test-e2e-serial
test-e2e-serial: ## Run serial E2E tests only: bootstrap/prompt_template/access_management (~42s) [RECORD_VIDEO=1]
	$(_E2E_PRE) $(_E2E_RUN) \
	  pytest tests/e2e/tests/ -m serial \
	  --override-ini="addopts=-v --tb=short --strict-markers --disable-warnings" $(_E2E_POST) \
	  2>&1 | sed 's/[0-9]* deselected, //g; s/, [0-9]* deselected//g'

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
test-all: $(VENV)/.installed $(NODE_MODULES)/.installed ## Run ALL tests: unit + E2E (with unified summary)
	@_rf=$$(mktemp); _t0=$$(date +%s); r_unit=0; r_mock_int=0; r_e2e=0; \
	export _RESULTS_FILE=$$_rf; \
	$(MAKE) --no-print-directory test-unit || r_unit=1; \
	$(MAKE) --no-print-directory test-mock-integration || r_mock_int=1; \
	$(MAKE) --no-print-directory test-e2e  || r_e2e=1; \
	_total_t=$$(( $$(date +%s) - $$_t0 )); \
	echo ""; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "\033[1m                        Full Test Suite Summary                          \033[0m\n"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	printf "  \033[1m%-18s %6s  %6s  %7s  %8s  %5s\033[0m\n" "Suite" "Passed" "Failed" "Skipped" "Coverage" "Time"; \
	printf "  %-18s %6s  %6s  %7s  %8s  %5s\n" "──────────────────" "──────" "──────" "───────" "────────" "─────"; \
	_tp=0; _tf=0; _ts=0; _tt=0; _ok=0; _n=0; _sep=0; \
	while IFS=: read -r name p f s cov t rc; do \
	  _n=$$(( $$_n + 1 )); \
	  if [ $$_n -eq 4 ] && [ $$_sep -eq 0 ]; then \
	    printf "  %-18s %6s  %6s  %7s  %8s  %5s\n" "── E2E ───────────" "──────" "──────" "───────" "────────" "─────"; \
	    _sep=1; \
	  fi; \
	  if [ "$$rc" = "0" ]; then _i="✅"; _ok=$$(( $$_ok + 1 )); else _i="❌"; fi; \
	  if [ "$$cov" != "—" ]; then \
	    printf "  %s %-16s %6s  %6s  %7s  \033[36m%8s\033[0m  %4ss\n" "$$_i" "$$name" "$$p" "$$f" "$$s" "$$cov" "$$t"; \
	  else \
	    printf "  %s %-16s %6s  %6s  %7s  %8s  %4ss\n" "$$_i" "$$name" "$$p" "$$f" "$$s" "$$cov" "$$t"; \
	  fi; \
	  _tp=$$(( $$_tp + $$p )); _tf=$$(( $$_tf + $$f )); _ts=$$(( $$_ts + $$s )); _tt=$$(( $$_tt + $$t )); \
	done < "$$_rf"; \
	printf "  %-18s %6s  %6s  %7s  %8s  %5s\n" "──────────────────" "──────" "──────" "───────" "────────" "─────"; \
	printf "  \033[1m%-18s %6s  %6s  %7s  %8s  %4ss\033[0m\n" "Total" "$$_tp" "$$_tf" "$$_ts" "" "$$_tt"; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	if [ $$_ok -eq $$_n ]; then printf "  ✅  \033[32mALL $$_n SUITES PASSED\033[0m  (wall %ss)\n" "$$_total_t"; \
	else printf "  ❌  \033[31m$$_ok/$$_n SUITES PASSED\033[0m  (wall %ss)\n" "$$_total_t"; fi; \
	printf "\033[1m══════════════════════════════════════════════════════════════════════════\033[0m\n"; \
	rm -f "$$_rf"; \
	[ "$$r_unit" = "0" ] && [ "$$r_mock_int" = "0" ] && [ "$$r_e2e" = "0" ]

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
	@echo "  make offline-bundle-export  Build images, export offline bundle, and package it"
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
	@echo "Lint:"
	@echo "  make lint              Run all lint checks"
	@echo "  make lint-backend      Run backend Ruff checks"
	@echo ""
	@echo "Mock Integration Tests (Docker):"
	@echo "  make test-mock-integration            Run mock integration tests (build + start + test)"
	@echo "  make test-mock-integration-build      Build mock integration test images"
	@echo "  make test-mock-integration-up         Start mock integration test environment"
	@echo "  make test-mock-integration-down       Stop mock integration test environment"
	@echo "  make test-mock-integration-logs       View mock integration test logs"
	@echo "  make test-mock-integration-parallel  Run mock integration tests in 3 parallel stacks"
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
	@echo "  make test-all          Run ALL tests (unit + E2E + mock integration) with overall summary"
	@echo ""

.DEFAULT_GOAL := help
