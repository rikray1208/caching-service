import json
import logging
import math
from collections.abc import Mapping
from typing import Any, Final

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from payload_cache.application.payload_input import UnequalListsError
from payload_cache.application.ports.payload_gateway import PayloadNotFoundError
from payload_cache.application.ports.transformer import TransformerUnavailableError
from payload_cache.exceptions import BaseError
from payload_cache.inbound.http.schemas import ErrorResponse

logger = logging.getLogger(__name__)

_HTTP_STATUS_BY_ERROR: Final[Mapping[type[BaseError], int]] = {
    PayloadNotFoundError: status.HTTP_404_NOT_FOUND,
    UnequalListsError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    TransformerUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}

_INTERNAL_SERVER_ERROR: Final = ErrorResponse(code="internal_server_error", message="Internal server error.")


class _AsciiJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, allow_nan=False, separators=(",", ":")).encode()


def setup_exception_handlers(app: FastAPI) -> None:
    app.exception_handler(RequestValidationError)(_handle_validation_error)
    app.add_exception_handler(BaseError, _handle_error)
    app.add_exception_handler(Exception, _handle_error)


def _finite_or_str(number: float) -> float | str:
    return number if math.isfinite(number) else str(number)


async def _handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    # FastAPI's own handler echoes the input, and two kinds of input made its 422 a 500: a lone surrogate,
    # which UTF-8 can't encode, and NaN or Infinity, which Python's JSON parser accepts but JSON can't hold.
    detail = jsonable_encoder(error.errors(), custom_encoder={float: _finite_or_str})
    return _AsciiJSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": detail})


async def _handle_error(request: Request, error: Exception) -> JSONResponse:
    for error_type, status_code in _HTTP_STATUS_BY_ERROR.items():
        if isinstance(error, error_type):
            body = ErrorResponse(code=error.code, message=str(error), details=error.details)
            return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))

    logger.error("Request %s %s failed", request.method, request.url.path, exc_info=error)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=_INTERNAL_SERVER_ERROR.model_dump(mode="json")
    )
