import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI

from payload_cache.health.router import router as health_router
from payload_cache.inbound.http.exception_handlers import setup_exception_handlers
from payload_cache.inbound.http.routes import router
from payload_cache.outbound.persistence.engine import create_async_session_factory, open_async_engine
from payload_cache.outbound.uppercase_transformer import UppercaseTransformer
from payload_cache.settings import LogLevel, Settings


@asynccontextmanager
async def lifespan(app: FastAPI, settings: Settings) -> AsyncIterator[None]:
    """Creates no tables: the container runs `alembic upgrade head` first, and the test fixtures migrate their own."""
    async with open_async_engine(settings.database) as engine:
        app.state["engine"] = engine
        app.state["session_factory"] = create_async_session_factory(engine)
        app.state["transformer"] = UppercaseTransformer(delay=settings.transformer_delay)
        yield


def setup_logging(level: LogLevel) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Uvicorn calls it with no arguments (`--factory`), so the settings come from the environment;
    tests pass their own. Nothing is read at import.
    """
    if settings is None:
        settings = Settings()
    setup_logging(settings.logging_level)

    app = FastAPI(title="Payload cache", version="0.1.0", lifespan=partial(lifespan, settings=settings))
    setup_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(router)
    return app
