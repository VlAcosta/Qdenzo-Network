# -*- coding: utf-8 -*-

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import settings
from ..models import Base

from .migrations import run_migrations


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create tables and run lightweight idempotent migrations.

    This function is safe to call on every startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await run_migrations(engine)
    logger.info("DB is ready.")


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Backward-compatible alias used across handlers.
# (Handlers import `session_scope`, but this module exposes `get_session`.)
session_scope = get_session
