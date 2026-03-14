"""Database migration utilities."""

import logging
import os
import subprocess
import sys
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Run database migrations using Alembic.

    This function runs pending migrations on application startup.
    It uses the DATABASE_URL environment variable for connection.
    """
    settings = get_settings()

    # Check if auto-migration is enabled
    if not settings.auto_migrate:
        logger.info("Auto-migration disabled, skipping")
        return

    # Get the alembic directory (parent of app/)
    alembic_dir = Path(__file__).parent.parent

    # Set DATABASE_URL from environment if not already set
    # This ensures migrations use the same connection as the app
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.warning("DATABASE_URL not set, migrations may fail")
        return

    logger.info("Running database migrations...")

    try:
        # Run alembic upgrade head
        result = subprocess.run(
            [
                sys.executable, "-m", "alembic", "upgrade", "head",
            ],
            cwd=str(alembic_dir),
            env={**os.environ, "PYTHONPATH": str(alembic_dir)},
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(f"Migration failed: {result.stderr}")
            raise RuntimeError(f"Migration failed: {result.stderr}")

        # Check if there were any migrations to run
        if "No migrations" in result.stdout or result.stdout.strip() == "":
            logger.info("Database is up to date")
        else:
            logger.info(f"Migrations applied: {result.stdout.strip()}")

    except FileNotFoundError:
        logger.warning("Alembic not found, skipping migrations")
    except Exception as e:
        logger.error(f"Error running migrations: {e}")
        raise


if __name__ == "__main__":
    # Allow running migrations directly
    logging.basicConfig(level=logging.INFO)
    run_migrations()
