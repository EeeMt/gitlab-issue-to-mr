"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import close_db, init_db
from app.scheduler import start_scheduler, stop_scheduler

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting GitLab Issue to MR Bot...")
    try:
        await init_db()
        logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Start scheduler in background
    scheduler_task = asyncio.create_task(start_scheduler())

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Stop scheduler
    await stop_scheduler()
    await scheduler_task

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
    """Health check endpoint."""
    return {"status": "healthy"}


# Import and include routers
from app.api import webhook, tasks, containers, stats, config

app.include_router(webhook.router, prefix="/api", tags=["webhook"])
app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(containers.router, prefix="/api", tags=["containers"])
app.include_router(stats.router, prefix="/api", tags=["stats"])
app.include_router(config.router, prefix="/api", tags=["config"])
