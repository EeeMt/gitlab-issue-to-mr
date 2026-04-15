# Mock Integration Test Performance Optimization

## Problem

`make test-mock-integration` takes ~31 minutes for 246 tests (sequential).
`make test-mock-integration-parallel` takes ~18 minutes (2-stack).
Target: sequential ≤ 8 min, parallel ≤ 3 min.

## Root Cause Analysis

Time breakdown for 246 tests with ~120 creating worker containers:

| Bottleneck | Time | Cause |
|-----------|------|-------|
| Scheduler pickup latency | ~5 min | `scheduler_interval=5s` (default, not set in compose) |
| Worker container lifecycle | ~5 min | 120 tasks × 7s / `MAX_CONCURRENCY=2` |
| Forced image pull | ~3 min | `pull_image(force=True)` over SSH per task |
| Polling overhead | ~3 min | `poll_interval=2.0` × 176 wait calls |
| Docker cp + pip install | ~7s/stack | Runtime test setup per stack |
| Explicit sleeps | ~1 min | Test-specific delays |
| Other HTTP/DB overhead | ~2 min | Network + query overhead |

## Design

### 1. Test Docker-Compose Tuning

Add to `docker-compose.mock-test.yml` environment for both backend and scheduler:

```yaml
SCHEDULER_INTERVAL: "1"    # was: unset (default 5s)
MAX_CONCURRENCY: "5"       # was: 2
```

`scheduler_interval` is already runtime-configurable via `/api/config` (validated 1-60s).
No backend code changes needed for this — just the compose env var.

**Expected savings:** ~4 min (scheduler latency) + ~3 min (higher concurrency)

### 2. Skip Forced Image Pull

Add `worker_skip_image_pull: bool = Field(default=False)` to `Settings` in `config.py`.

In `worker.py:execute_task()`, wrap the pull call:
```python
if not settings.worker_skip_image_pull:
    self.docker.pull_image(settings.worker_image, force=True)
```

Test compose sets `WORKER_SKIP_IMAGE_PULL: "true"`.

**Expected savings:** ~2-3 min (120 tasks × 1.5s per forced pull over SSH)

### 3. Dedicated Backend Test Image

Create `backend/tests/mock_integration/Dockerfile.backend-test`:
```dockerfile
FROM codify-backend:latest
RUN pip install pytest pytest-asyncio httpx
COPY backend/tests/ /app/tests/
```

Built by `make test-mock-integration-build`.

In `docker-compose.mock-test.yml`, change backend service:
```yaml
backend:
  image: codify-backend-test:latest
  volumes:
    - ../../backend/tests:/app/tests  # fast iteration override
```

Remove `docker cp` and `pip install` steps from `scripts/run-mock-stack.sh`.

**Expected savings:** ~5-7s per stack startup

### 4. Reduce Poll Interval

In `conftest.py`, change `wait_for_task_status` default:
```python
poll_interval: float = 0.5,  # was: 2.0
```

**Expected savings:** ~2 min (faster status detection across 176 calls)

### 5. Three-Stack Parallel

Split test files into 3 groups (A/B/C) balanced by execution weight.
Each stack gets independent Docker Compose environment.

Port allocation:
- Stack A: mock=19000, backend=18000
- Stack B: mock=19001, backend=18001
- Stack C: mock=19002, backend=18002

Update `Makefile`:
- `MOCK_GROUP_A`, `MOCK_GROUP_B`, `MOCK_GROUP_C` variables
- `test-mock-integration-parallel` launches 3 background processes

### 6. Test Code Adjustments

- `test_scheduling.py`: Query `MAX_CONCURRENCY` from config API and create `N+1` tasks
  instead of hardcoded 3
- Update comments referencing `MAX_CONCURRENCY=2` across test files
- Adjust `test_gap_analysis.py` comments (behavior unchanged, just different concurrency)

## Expected Results

### Sequential (`make test-mock-integration`)
- Before: ~31 min
- After: ~6-8 min (1s scheduler + 5 concurrency + skip pull + 0.5s poll)

### Parallel (`make test-mock-integration-parallel`)
- Before: ~18 min (2 stacks)
- After: ~3-4 min (3 stacks × faster settings)

## Files Changed

| File | Change |
|------|--------|
| `backend/app/config.py` | Add `worker_skip_image_pull` field |
| `backend/app/core/worker.py` | Conditional image pull |
| `backend/tests/mock_integration/docker-compose.mock-test.yml` | SCHEDULER_INTERVAL, MAX_CONCURRENCY, image change |
| `backend/tests/mock_integration/Dockerfile.backend-test` | New: dedicated test image |
| `backend/tests/mock_integration/conftest.py` | poll_interval default 0.5 |
| `backend/tests/mock_integration/test_scheduling.py` | Dynamic MAX_CONCURRENCY |
| `backend/tests/mock_integration/test_gap_analysis.py` | Comment updates |
| `scripts/run-mock-stack.sh` | Remove docker cp + pip install steps |
| `Makefile` | 3-stack parallel, GROUP_C, build test image |

## Risks

- **Docker host load**: 3 stacks × 5 concurrency = up to 15 simultaneous worker containers.
  The remote host (192.168.50.129) needs sufficient CPU/memory.
- **Flaky concurrency tests**: Higher concurrency may expose timing issues.
  Mitigation: keep `test_mutex_and_scheduling.py` last in its group.
- **Volume mount vs baked-in tests**: Volume mount takes precedence;
  if tests directory structure changes, both need updating.
