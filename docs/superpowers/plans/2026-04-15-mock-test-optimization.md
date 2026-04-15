# Mock Integration Test Performance Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce mock integration test runtime from ~31 min sequential / ~18 min parallel to ~6-8 min sequential / ~3-4 min parallel.

**Architecture:** Tune scheduler/concurrency settings in test compose, skip forced Docker image pulls, build a dedicated test image with pre-installed deps, reduce poll intervals, and split into 3 parallel stacks.

**Tech Stack:** Docker Compose, bash, Python/pytest, Makefile

**Spec:** `docs/superpowers/specs/2026-04-15-mock-test-optimization-design.md`

---

### Task 1: Add `worker_skip_image_pull` Config Flag

**Files:**
- Modify: `backend/app/config.py:137` (add new field after `worker_container_prefix`)
- Modify: `backend/app/core/worker.py:886-891` (wrap pull_image call)

- [ ] **Step 1: Add config field**

In `backend/app/config.py`, after line 137 (`worker_container_prefix`), add:

```python
    worker_skip_image_pull: bool = Field(default=False)  # Skip pull_image for local/test environments
```

- [ ] **Step 2: Wrap the pull call in worker.py**

In `backend/app/core/worker.py`, replace lines 886-891:

```python
        try:
            # Pull worker image
            try:
                self.docker.pull_image(settings.worker_image, force=True)
            except Exception as e:
                logger.warning(f"Failed to pull image: {e}, trying to use existing")
```

With:

```python
        try:
            # Pull worker image (skipped when worker_skip_image_pull is set)
            if not settings.worker_skip_image_pull:
                try:
                    self.docker.pull_image(settings.worker_image, force=True)
                except Exception as e:
                    logger.warning(f"Failed to pull image: {e}, trying to use existing")
```

- [ ] **Step 3: Verify backend unit tests still pass**

Run: `cd backend && python -m pytest tests/unit/ -x -q 2>&1 | tail -5`
Expected: All 1315 tests pass (no unit tests exercise pull_image directly)

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py backend/app/core/worker.py
git commit -m "feat: add worker_skip_image_pull config to skip Docker pull in tests"
```

---

### Task 2: Tune Docker-Compose Test Settings

**Files:**
- Modify: `backend/tests/mock_integration/docker-compose.mock-test.yml:48-101`

- [ ] **Step 1: Add SCHEDULER_INTERVAL and WORKER_SKIP_IMAGE_PULL, bump MAX_CONCURRENCY**

In `docker-compose.mock-test.yml`, for the **backend** service environment (after line 61), add:

```yaml
      SCHEDULER_INTERVAL: "1"
      WORKER_SKIP_IMAGE_PULL: "true"
```

Change line 60 from `MAX_CONCURRENCY: "2"` to:
```yaml
      MAX_CONCURRENCY: "5"
```

- [ ] **Step 2: Same changes for scheduler service**

In the **scheduler** service environment (after line 98), add:

```yaml
      SCHEDULER_INTERVAL: "1"
      WORKER_SKIP_IMAGE_PULL: "true"
```

Change line 97 from `MAX_CONCURRENCY: "2"` to:
```yaml
      MAX_CONCURRENCY: "5"
```

- [ ] **Step 3: Reduce health check intervals**

For **backend** service healthcheck (lines 72-76), change:
```yaml
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 2s
      timeout: 5s
      retries: 15
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/mock_integration/docker-compose.mock-test.yml
git commit -m "perf: tune test compose — scheduler_interval=1, max_concurrency=5, skip pull"
```

---

### Task 3: Reduce Default Poll Interval in Test Helpers

**Files:**
- Modify: `backend/tests/mock_integration/conftest.py:230`

- [ ] **Step 1: Change default poll_interval**

In `backend/tests/mock_integration/conftest.py`, change line 230 from:
```python
    poll_interval: float = 2.0,
```
To:
```python
    poll_interval: float = 0.5,
```

- [ ] **Step 2: Commit**

```bash
git add backend/tests/mock_integration/conftest.py
git commit -m "perf: reduce wait_for_task_status poll_interval from 2.0 to 0.5 seconds"
```

---

### Task 4: Update Tests Referencing MAX_CONCURRENCY=2

**Files:**
- Modify: `backend/tests/mock_integration/test_scheduling.py:130-133`
- Modify: `backend/tests/mock_integration/test_gap_analysis.py:188-191,352-355`

- [ ] **Step 1: Fix test_scheduling.py — dynamic concurrency**

In `test_scheduling.py`, replace lines 130-133:
```python
        """Create more tasks than MAX_CONCURRENCY, verify they all eventually complete."""
        # docker-compose has MAX_CONCURRENCY=2, so create 3 tasks
        task_ids = []
        for i in range(3):
```

With:
```python
        """Create more tasks than MAX_CONCURRENCY, verify they all eventually complete."""
        # Fetch current MAX_CONCURRENCY from config and create one extra task
        resp = await http_client.get(
            f"{backend_url}/api/config",
            headers=admin_auth_headers,
        )
        max_conc = resp.json().get("runtime", {}).get("max_concurrency", 5)
        num_tasks = max_conc + 1

        task_ids = []
        for i in range(num_tasks):
```

- [ ] **Step 2: Fix test_gap_analysis.py — update comments**

In `test_gap_analysis.py`, change lines 188-191 from:
```python
        """Create tasks for 2 different issues -- both should run concurrently.

        docker-compose has MAX_CONCURRENCY=2, so two tasks
        should start roughly at the same time.
        """
```
To:
```python
        """Create tasks for 2 different issues -- both should run concurrently.

        MAX_CONCURRENCY >= 2, so two tasks should start roughly at the same time.
        """
```

And change lines 352-355 from:
```python
        """Create P2, P1, P0 tasks in that order -- verify P0 starts first.

        With MAX_CONCURRENCY=2 and claude_delay=5, the first task picked
        should be P0 (highest priority), then P1, then P2.
        """
```
To:
```python
        """Create P2, P1, P0 tasks in that order -- verify P0 starts first.

        With MAX_CONCURRENCY >= 2 and claude_delay=5, the first task picked
        should be P0 (highest priority), then P1, then P2.
        """
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/mock_integration/test_scheduling.py backend/tests/mock_integration/test_gap_analysis.py
git commit -m "fix: update mock tests for configurable MAX_CONCURRENCY"
```

---

### Task 5: Create Dedicated Backend Test Image

**Files:**
- Create: `backend/tests/mock_integration/Dockerfile.backend-test`
- Modify: `backend/tests/mock_integration/docker-compose.mock-test.yml:44,66,82`
- Modify: `Makefile` (test-mock-integration-build target)
- Modify: `scripts/run-mock-stack.sh` (remove docker cp and pip install)

- [ ] **Step 1: Create Dockerfile.backend-test**

Create `backend/tests/mock_integration/Dockerfile.backend-test`:
```dockerfile
# Extends the production backend image with test dependencies and test code.
# Test files can be overridden at runtime via volume mount for fast iteration.
FROM codify-backend:latest

# Install test dependencies (baked into image to avoid runtime pip install)
RUN pip install pytest pytest-asyncio httpx

# Copy test files (overridden by volume mount in docker-compose for dev)
COPY backend/tests/ /app/tests/
```

- [ ] **Step 2: Add build command to Makefile**

In `Makefile`, in the `test-mock-integration-build` target (currently lines 215-218), add the new build after the existing two:

```makefile
.PHONY: test-mock-integration-build
test-mock-integration-build: ## Build images for mock integration tests
	docker build -f $(PROJECT_ROOT)/deploy/Dockerfile.backend -t codify-backend:latest $(PROJECT_ROOT)
	docker build -f $(PROJECT_ROOT)/backend/tests/mock_integration/Dockerfile.backend-test -t codify-backend-test:latest $(PROJECT_ROOT)
	docker build -f $(PROJECT_ROOT)/backend/tests/mock_integration/mock_server/Dockerfile -t codify-mock-services:latest $(PROJECT_ROOT)
	docker build -f $(PROJECT_ROOT)/backend/tests/mock_integration/fake_claude/Dockerfile.worker-test -t codify-worker-test:latest $(PROJECT_ROOT)
	@echo "Mock integration test images built: codify-backend-test:latest, codify-mock-services:latest, codify-worker-test:latest"
```

Note: We now also build `codify-backend:latest` first (since `codify-backend-test` depends on it via `FROM`), then the test image.

- [ ] **Step 3: Update docker-compose to use test image + volume mount**

In `docker-compose.mock-test.yml`:

Change line 44 (`image: codify-backend:latest`) for backend service to:
```yaml
    image: codify-backend-test:latest
```

Add volume mount for test iteration (add to backend volumes, after line 66):
```yaml
      - ../../../backend/tests:/app/tests
```

Change line 82 (`image: codify-backend:latest`) for scheduler service to:
```yaml
    image: codify-backend-test:latest
```

- [ ] **Step 4: Simplify run-mock-stack.sh**

In `scripts/run-mock-stack.sh`, remove the "Copy tests into container" and "pip install" blocks. The section between `compose up` and `# Build pytest args` should be replaced.

Remove these lines (approximately lines 79-87):
```bash
# --- Copy tests into container ---
docker cp "$SOURCE_ROOT/backend/tests" "$CONTAINER:/tmp/tests"
docker exec "$CONTAINER" bash -c \
  "mkdir -p /app/tests && cp /tmp/tests/__init__.py /app/tests/ 2>/dev/null; \
   rm -rf /app/tests/mock_integration && cp -r /tmp/tests/mock_integration /app/tests/mock_integration"
docker exec "$CONTAINER" pip install pytest pytest-asyncio httpx --quiet 2>/dev/null
```

The `-s SOURCE_ROOT` flag is still needed for other potential uses, but the docker cp/pip install are no longer necessary since deps are in the image and tests are mounted as a volume.

- [ ] **Step 5: Verify build works**

Run: `make test-mock-integration-build`
Expected: All 4 images built successfully

- [ ] **Step 6: Commit**

```bash
git add backend/tests/mock_integration/Dockerfile.backend-test \
        backend/tests/mock_integration/docker-compose.mock-test.yml \
        Makefile scripts/run-mock-stack.sh
git commit -m "feat: dedicated backend test image with pre-installed deps + volume mount"
```

---

### Task 6: Three-Stack Parallel Target

**Files:**
- Modify: `Makefile` (MOCK_GROUP_A/B/C variables and parallel target)

- [ ] **Step 1: Rebalance test groups into 3**

Replace the existing `MOCK_GROUP_A` and `MOCK_GROUP_B` variables with three groups. Balance by test count:
- Group A: ~82 tests (heavy on container-wait tests)
- Group B: ~82 tests
- Group C: ~81 tests

```makefile
# Three-stack test groups (balanced by test count, ~82 each)
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
```

- [ ] **Step 2: Update parallel target to 3 stacks**

Replace the existing `test-mock-integration-parallel` target with:

```makefile
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
```

- [ ] **Step 3: Update help text**

Change the mock-integration-parallel help line from:
```
  make test-mock-integration-parallel  Run mock integration tests in 2 parallel stacks
```
To:
```
  make test-mock-integration-parallel  Run mock integration tests in 3 parallel stacks
```

- [ ] **Step 4: Dry-run both targets**

Run: `make -n test-mock-integration 2>&1 | head -10`
Run: `make -n test-mock-integration-parallel 2>&1 | head -20`
Expected: Valid expanded commands, no syntax errors

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "perf: 3-stack parallel mock integration tests"
```

---

### Task 7: Run Sequential Tests — Verify Optimization

**Files:** None (verification only)

- [ ] **Step 1: Run sequential mock integration tests**

Run: `make test-mock-integration`
Expected: All 245-246 tests pass. Runtime should be ~6-8 min (was ~31 min).

- [ ] **Step 2: Note the runtime**

Record the actual runtime for comparison. If > 10 min, check if `SCHEDULER_INTERVAL=1` and `MAX_CONCURRENCY=5` are taking effect by looking at scheduler logs:
```bash
docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml logs scheduler | grep 'interval\|concurrency' | head -5
```

---

### Task 8: Run Parallel Tests — Verify 3-Stack Performance

**Files:** None (verification only)

- [ ] **Step 1: Run parallel mock integration tests**

Run: `make test-mock-integration-parallel`
Expected: All 3 stacks pass. Wall clock time should be ~3-5 min.

- [ ] **Step 2: If any stack fails, check logs**

Failed stacks are usually timing-sensitive concurrency tests. Check which tests failed:
```bash
# Look for FAILED in the output for the specific stack letter
```

If `test_mutex_and_scheduling.py` fails, move it to the last position in its group (it's timing-sensitive under heavy Docker load).

- [ ] **Step 3: Final commit with timing results**

```bash
git add -A
git commit -m "verify: mock integration tests optimized — sequential Xmin, parallel Ymin"
```
