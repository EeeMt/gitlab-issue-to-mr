"""FastAPI application entry point."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.database import AsyncSessionLocal, close_db, get_db, init_db
from app.dependencies.auth import require_admin_user, require_authenticated_user
from app.migrations import run_migrations
from app.middleware.trace import TraceMiddleware, get_trace_id
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
    await close_db()
    logger.info("Database connection closed")


app = FastAPI(
    title="Codify",
    description="AI-powered code generation from GitLab Issues",
    version="0.1.0",
    lifespan=lifespan,
)

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
    health_status = {"status": "healthy", "checks": {}, "trace_id": trace_id}

    # Check database connection
    try:
        from app.database import engine
        from sqlalchemy import text
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
from app.api import admin_users, auth, issues, tasks, containers, stats, config, config_integration, config_runtime, mattermost, oidc, project_webhooks, prompt_templates, projects

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
    dependencies=[Depends(require_admin_user)],
)
app.include_router(
    admin_users.router,
    prefix="/api",
    tags=["admin-users"],
    dependencies=[Depends(require_admin_user)],
)
