"""FastAPI application entry point."""

import asyncio
import re
import time
from contextlib import asynccontextmanager
from email.message import Message
from json import JSONDecodeError, loads
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from app.api.task_command_routes import CreateCommandRequest
from app.config import get_settings
from app.core.docker_client import close_docker_clients
from app.core.harness_execution_policy import require_explicit_harness_execution_mode
from app.core.harness_protocol import is_valid_command_text, normalize_command_id
from app.core.logging import get_logger, setup_logging
from app.database import AsyncSessionLocal, close_db, get_db, init_db
from app.dependencies.auth import require_admin_user, require_authenticated_user
from app.middleware.trace import TraceMiddleware, get_trace_id
from app.migrations import run_migrations
from app.runtime_config import load_runtime_config_from_db, refresh_runtime_config_if_stale

settings = get_settings()

# Initialize loguru logging
setup_logging()
logger = get_logger(__name__)


async def _event_loop_lag_monitor():
    """Background task that measures event loop lag.

    Wakes up every 0.1s. If actual elapsed time is much longer, the
    event loop was blocked by synchronous code.
    """
    while True:
        t = time.time()
        await asyncio.sleep(0.1)
        lag = time.time() - t - 0.1
        if lag > 1.0:
            logger.warning(f"[EVENT LOOP LAG] {lag:.3f}s — event loop was blocked")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting Codify...")
    require_explicit_harness_execution_mode(settings)

    # Run database migrations first
    try:
        run_migrations()
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise

    # Initialize database connection
    try:
        await init_db()
        await load_runtime_config_from_db()
        logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Start event loop lag monitor
    lag_monitor = asyncio.create_task(_event_loop_lag_monitor())

    yield

    # Shutdown
    logger.info("Shutting down...")

    lag_monitor.cancel()
    close_docker_clients()
    await close_db()
    logger.info("Database connection closed")


app = FastAPI(
    title="Codify",
    description="AI-powered code generation from GitLab Issues",
    version="0.1.0",
    lifespan=lifespan,
)

_TASK_COMMAND_ITEM_PATH_RE = re.compile(
    r"^/api/tasks/(?P<task_id>[^/]+)/commands/(?P<command_id>[^/]+)$"
)
# A valid request with a fully escaped 4,000 UTF-16-unit text needs at most
# roughly 24 KiB for ``text`` plus its small JSON envelope.  Keep the ingress
# bound comfortably above that, while refusing arbitrary unauthenticated JSON
# before it is buffered or decoded.
_MAX_TASK_COMMAND_REQUEST_BYTES = 32 * 1024
_TASK_ID_PATH_RE = re.compile(r"^[0-9]{1,10}$")
_MAX_TASK_ID = 2_147_483_647


def _command_preflight_error(*, code: str, message: str) -> JSONResponse:
    """Return a non-reflecting public response before auth or DB access."""
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": code, "message": message}},
    )


def _is_json_content_type(request: Request) -> bool:
    """Match FastAPI's JSON media type boundary without reading other bodies."""
    content_type = request.headers.get("content-type")
    if not content_type:
        return True
    message = Message()
    message["content-type"] = content_type
    return (
        message.get_content_maintype() == "application"
        and (
            message.get_content_subtype() == "json"
            or message.get_content_subtype().endswith("+json")
        )
    )


def _is_valid_task_id_path_segment(task_id: str) -> bool:
    """Validate the integer route parameter before auth/config dependencies."""
    if _TASK_ID_PATH_RE.fullmatch(task_id) is None:
        return False
    return 1 <= int(task_id) <= _MAX_TASK_ID


async def _read_bounded_task_command_body(request: Request) -> bytes | None:
    """Buffer a small command body once and make the exact bytes replayable.

    ``Request.json()``/``Request.body()`` have no application-level bound and
    cache the complete input.  Command preflight intentionally precedes auth,
    so it must bound both declared and chunked bodies itself.  Assigning the
    bounded bytes to Starlette's body cache preserves normal downstream body
    parsing without a second receive consumption.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_TASK_COMMAND_REQUEST_BYTES:
                return None
        except ValueError:
            return None

    buffered = bytearray()
    try:
        async for chunk in request.stream():
            if len(buffered) + len(chunk) > _MAX_TASK_COMMAND_REQUEST_BYTES:
                return None
            buffered.extend(chunk)
    except (ClientDisconnect, RuntimeError):
        return None
    body = bytes(buffered)
    request._body = body  # type: ignore[attr-defined]  # Starlette replay cache.
    return body

# Register Trace middleware
app.add_middleware(TraceMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8880",
        "http://127.0.0.1:8880",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def sync_runtime_config(request: Request, call_next):
    """Keep each worker's in-memory runtime config in sync with the database."""
    if request.url.path.startswith("/api/"):
        # API tests often override get_db with mocks; avoid bypassing those
        # overrides by opening a separate real AsyncSession in middleware.
        if get_db not in request.app.dependency_overrides:
            async with AsyncSessionLocal() as session:
                await refresh_runtime_config_if_stale(session)
        request.state.runtime_config_synced = True
    return await call_next(request)


@app.middleware("http")
async def log_slow_requests(request: Request, call_next):
    """Log requests that take more than 2 seconds."""
    t0 = time.time()
    path = request.url.path
    # Log when the request arrives for task detail endpoints
    if path.startswith("/tasks/") and "logs" not in path and request.method == "GET":
        logger.info(f"[REQUEST ARRIVED] {request.method} {path} t={t0:.3f}")
    response = await call_next(request)
    elapsed = time.time() - t0
    if elapsed > 2.0 and "logs" not in path:
        logger.warning(
            f"[SLOW REQUEST] {request.method} {path} "
            f"total={elapsed:.3f}s status={response.status_code}"
        )
    return response


@app.middleware("http")
async def preflight_task_command_input(request: Request, call_next):
    """Reject unsafe command inputs before config sync, auth, and router deps.

    The task-command router is included with a router-level auth dependency and
    every API request otherwise triggers runtime-config DB synchronization.
    This outer middleware is therefore the only layer that can provide the
    frozen fail-fast 422 contract without performing either operation first.
    """
    match = _TASK_COMMAND_ITEM_PATH_RE.fullmatch(request.scope.get("path", ""))
    if match is not None and request.method in {"GET", "PUT"}:
        task_id = match.group("task_id")
        if not _is_valid_task_id_path_segment(task_id):
            return _command_preflight_error(
                code="invalid_task_id",
                message="The task ID format is invalid.",
            )
        command_id = normalize_command_id(match.group("command_id"))
        if command_id is None:
            return _command_preflight_error(
                code="invalid_command_id",
                message="The command ID format is invalid.",
            )
        # Router matching needs the canonical ID, but raw_path/query_string
        # are transport facts.  In particular, do not erase a caller's exact
        # task segment or percent-encoding while canonicalizing command_id.
        canonical_path = f"/api/tasks/{task_id}/commands/{command_id}"
        request.scope["path"] = canonical_path
        if request.method == "PUT":
            if not _is_json_content_type(request):
                return _command_preflight_error(
                    code="invalid_command_payload",
                    message="The command payload is invalid.",
                )
            body = await _read_bounded_task_command_body(request)
            if body is None:
                return _command_preflight_error(
                    code="payload_too_large",
                    message="The command content exceeds the allowed length.",
                )
            try:
                payload = loads(body)
            except (JSONDecodeError, UnicodeDecodeError):
                return _command_preflight_error(
                    code="invalid_command_payload",
                    message="The command payload is invalid.",
                )
            try:
                validated = CreateCommandRequest.model_validate(payload)
            except ValidationError:
                return _command_preflight_error(
                    code="invalid_command_payload",
                    message="The command payload is invalid.",
                )
            if not is_valid_command_text(validated.text):
                return _command_preflight_error(
                    code="payload_too_large",
                    message="The command content exceeds the allowed length.",
                )
    return await call_next(request)


# Unified exception handler
@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    trace_id = get_trace_id(request)

    logger.bind(trace_id=trace_id).error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)}"
    )

    return JSONResponse(
        status_code=500,
        headers={"X-Trace-ID": trace_id},
        content={
            "error": "Internal server error",
            "trace_id": trace_id,
            "type": type(exc).__name__,
        }
    )


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "name": "Codify",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health(request: Request) -> dict:
    """Health check endpoint with dependency checks."""
    trace_id = get_trace_id(request)
    health_status = {
        "status": "healthy",
        "checks": {},
        "trace_id": trace_id,
        # Plan §4.8: readiness displays the current execution mode so a
        # deployment preflight can compare Backend/Scheduler values.
        "harness_execution_mode": get_settings().harness_execution_mode,
    }

    # Check database connection
    try:
        from sqlalchemy import text

        from app.database import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["checks"]["database"] = f"error: {str(e)[:50]}"
        health_status["status"] = "unhealthy"

    # Check Docker connection
    try:
        import docker
        client = docker.from_env()
        client.ping()
        health_status["checks"]["docker"] = "ok"
    except Exception as e:
        health_status["checks"]["docker"] = f"error: {str(e)[:50]}"
        health_status["status"] = "degraded"

    # Set appropriate status code
    status_code = 200 if health_status["status"] == "healthy" else 503

    return JSONResponse(content=health_status, status_code=status_code)


# Import and include routers
from app.api import (
    admin_users,
    announcement,
    auth,
    ci_failures,
    config,
    config_integration,
    config_runtime,
    containers,
    harness_catalog,
    issues,
    maintenance,
    mattermost,
    oidc,
    project_webhooks,
    projects,
    prompt_templates,
    providers,
    skills,
    stats,
    system_statistics,
    task_command_routes,
    tasks,
    usage_limits,
    webhook_handler,
    worker_profiles,
    worker_shared_configuration,
)

app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(
    issues.router,
    prefix="/api",
    tags=["issues"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    tasks.router,
    prefix="/api",
    tags=["tasks"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    task_command_routes.router,
    prefix="/api",
    tags=["task-commands"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    harness_catalog.router,
    prefix="/api",
    tags=["harness-catalog"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    projects.router,
    prefix="/api",
    tags=["projects"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    containers.router,
    prefix="/api",
    tags=["containers"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    stats.router,
    prefix="/api",
    tags=["stats"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    config.router,
    prefix="/api",
    tags=["config"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    config_integration.router,
    prefix="/api",
    tags=["config"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    config_runtime.router,
    prefix="/api",
    tags=["config"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    maintenance.router,
    prefix="/api",
    tags=["config"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    oidc.router,
    prefix="/api",
    tags=["config"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    mattermost.router,
    prefix="/api",
    tags=["config"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    project_webhooks.router,
    prefix="/api",
    tags=["config"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    prompt_templates.router,
    prefix="/api",
    tags=["prompt-templates"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    admin_users.router,
    prefix="/api",
    tags=["admin-users"],
    dependencies=[Depends(require_admin_user)],
)
app.include_router(
    system_statistics.router,
    prefix="/api",
    tags=["system-statistics"],
    dependencies=[Depends(require_admin_user)],
)
app.include_router(
    providers.router,
    prefix="/api",
    tags=["providers"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    worker_profiles.router,
    prefix="/api",
    tags=["worker-profiles"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    worker_shared_configuration.router,
    prefix="/api",
    tags=["worker-shared-configuration"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    skills.router,
    prefix="/api",
    tags=["skills"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    usage_limits.router,
    prefix="/api",
    tags=["usage-limits"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    ci_failures.router,
    prefix="/api",
    tags=["ci-failures"],
    dependencies=[Depends(require_authenticated_user)],
)
app.include_router(
    announcement.router,
    prefix="/api",
    tags=["announcement"],
)
# Webhook receiver — no auth (verified via X-Gitlab-Token header)
app.include_router(webhook_handler.webhook_router, prefix="/api", tags=["webhook"])
# Webhook event log — requires authentication
app.include_router(
    webhook_handler.events_router,
    prefix="/api",
    tags=["webhook"],
    dependencies=[Depends(require_authenticated_user)],
)
