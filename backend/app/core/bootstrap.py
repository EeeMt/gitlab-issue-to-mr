"""System bootstrap and initialization management."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemBootstrap, User


async def get_bootstrap_state(db: AsyncSession) -> SystemBootstrap:
    """
    Get the current system bootstrap state.
    
    Args:
        db: Database session
        
    Returns:
        SystemBootstrap record
    """
    result = await db.execute(
        select(SystemBootstrap).where(SystemBootstrap.id == 1)
    )
    bootstrap = result.scalar_one_or_none()
    
    if bootstrap is None:
        # Create initial bootstrap record if it doesn't exist
        bootstrap = SystemBootstrap(id=1, initialized=False)
        db.add(bootstrap)
        await db.flush()
    
    return bootstrap


async def is_system_initialized(db: AsyncSession) -> bool:
    """
    Check if the system has been initialized.
    
    Args:
        db: Database session
        
    Returns:
        True if system is initialized, False otherwise
    """
    bootstrap = await get_bootstrap_state(db)
    return bootstrap.initialized


async def initialize_system(
    db: AsyncSession,
    admin_user: User,
) -> SystemBootstrap:
    """
    Mark the system as initialized with the initial admin user.
    
    Args:
        db: Database session
        admin_user: The initial admin user
        
    Returns:
        Updated SystemBootstrap record
    """
    bootstrap = await get_bootstrap_state(db)
    bootstrap.initialized = True
    bootstrap.initial_admin_user_id = admin_user.id
    bootstrap.initialized_at = datetime.utcnow()
    
    await db.flush()
    return bootstrap


async def get_initial_admin(db: AsyncSession) -> Optional[User]:
    """
    Get the initial admin user if system is initialized.
    
    Args:
        db: Database session
        
    Returns:
        Initial admin user or None
    """
    bootstrap = await get_bootstrap_state(db)
    if not bootstrap.initial_admin_user_id:
        return None
    
    result = await db.execute(
        select(User).where(User.id == bootstrap.initial_admin_user_id)
    )
    return result.scalar_one_or_none()
