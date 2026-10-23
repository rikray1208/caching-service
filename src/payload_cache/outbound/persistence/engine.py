from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from payload_cache.settings import DatabaseSettings


@asynccontextmanager
async def open_async_engine(settings: DatabaseSettings) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        settings.create_url(),
        pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


def create_async_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
