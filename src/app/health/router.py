import logging
from typing import Final

import anyio
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.common.inbound.http.dependencies import EngineDependency

PROBE_TIMEOUT_SECONDS: Final = 1

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health(engine: EngineDependency) -> JSONResponse:
    try:
        with anyio.fail_after(PROBE_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (OSError, DBAPIError) as error:
        logger.warning("Health check failed, the database is unavailable: %r", error)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": "unavailable"},
        )

    return JSONResponse(content={"status": "healthy"})
