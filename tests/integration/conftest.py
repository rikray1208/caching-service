import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from typing import Final

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, NullPool, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from payload_cache.outbound.persistence.engine import create_async_session_factory, open_async_engine
from payload_cache.outbound.persistence.models import Base
from payload_cache.run import create_app
from payload_cache.settings import DatabaseSettings, Settings

TEST_INFRA_FLAG: Final[str] = "IT_TEST_INFRA"


@pytest.fixture(scope="session", autouse=True)
def it_require_test_infra() -> None:
    """
    Every test here needs the test project's PostgreSQL, which only `scripts/start-test-infra.sh` starts.
    Skips rather than fails, so `uv run pytest` on the host still runs the unit tests.
    """
    if os.getenv(TEST_INFRA_FLAG) != "1":
        pytest.skip(f"needs the test PostgreSQL: run scripts/start-test-infra.sh, which sets {TEST_INFRA_FLAG}=1")


@pytest.fixture(scope="session")
def it_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


@pytest.fixture(scope="session")
def it_maintenance_db_engine(it_database_settings: DatabaseSettings) -> Iterator[Engine]:
    """`CREATE DATABASE` cannot run in a transaction, hence AUTOCOMMIT; `NullPool` keeps an idle worker unconnected."""
    url = it_database_settings.create_url(drivername="postgresql+psycopg").set(database="postgres")
    engine = create_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def it_worker_database_settings(
    it_database_settings: DatabaseSettings,
    it_maintenance_db_engine: Engine,
    pytestconfig: pytest.Config,
    worker_id: str,
) -> DatabaseSettings:
    """
    Own migrated database per worker; `worker_id` is `master` when pytest runs without `-n`.
    Alembic runs in a subprocess: `env.py` reconfigures global logging. It runs from pytest's root folder,
    next to `alembic.ini`, and reads the database from `POSTGRES_DB`, as `env.py` builds its own settings.
    """
    settings = it_database_settings.model_copy(update={"db": f"{it_database_settings.db}_{worker_id}"})

    with it_maintenance_db_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{settings.db}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{settings.db}"'))

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=pytestconfig.rootpath,
        env=os.environ | {"POSTGRES_DB": settings.db},
        check=True,
    )

    return settings


@pytest.fixture(scope="session")
def it_worker_db_engine(it_worker_database_settings: DatabaseSettings) -> Iterator[Engine]:
    """Synchronous, so that `it_db_clean` serves the synchronous API tests as well as the async ones."""
    url = it_worker_database_settings.create_url(drivername="postgresql+psycopg")
    engine = create_engine(url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def it_db_clean(it_worker_db_engine: Engine) -> None:
    table_names = [table.name for table in Base.metadata.sorted_tables]
    if not table_names:
        return

    sql = "TRUNCATE " + ", ".join(f'"{name}"' for name in table_names) + " RESTART IDENTITY CASCADE;"

    with it_worker_db_engine.begin() as connection:
        connection.execute(text(sql))


@pytest.fixture
async def it_engine(it_worker_database_settings: DatabaseSettings) -> AsyncIterator[AsyncEngine]:
    async with open_async_engine(it_worker_database_settings) as engine:
        yield engine


@pytest.fixture
def it_sessionmaker(it_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_async_session_factory(it_engine)


@pytest.fixture
def app_settings(it_worker_database_settings: DatabaseSettings) -> Settings:
    return Settings(database=it_worker_database_settings)


@pytest.fixture
def app(app_settings: Settings, it_db_clean: None) -> FastAPI:
    return create_app(app_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:  # runs the lifespan, which opens the app's engine on the worker's database
        yield client
