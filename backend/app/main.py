"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import close_db, init_db
from app.migrations import run_migrations
from app.runtime_config import load_runtime_config_from_db

settings = get_settings()

# Configure logging with structured format
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting GitLab Issue to MR Bot...")

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

    yield

    # Shutdown
    logger.info("Shutting down...")

    await close_db()
    logger.info("Database connection closed")


app = FastAPI(
    title="GitLab Issue to MR Bot",
    description="AI-powered code generation from GitLab Issues",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "name": "GitLab Issue to MR Bot",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health() -> dict:
    """Health check endpoint with dependency checks."""
    health_status = {"status": "healthy", "checks": {}}

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

    from fastapi.responses import JSONResponse
    return JSONResponse(content=health_status, status_code=status_code)


# Import and include routers
from app.api import webhook, tasks, containers, stats, config

app.include_router(webhook.router, prefix="/api", tags=["webhook"])
app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(containers.router, prefix="/api", tags=["containers"])
app.include_router(stats.router, prefix="/api", tags=["stats"])
app.include_router(config.router, prefix="/api", tags=["config"])
