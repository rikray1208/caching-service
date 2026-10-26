import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

import httpx2

_MAX_QUOTED_TEXT: Final = 300


class ServiceError(Exception):
    """The service is unreachable or answered with an error. The CLI handles every such case the same way."""


@dataclass(frozen=True)
class CreatedPayload:
    id: str
    created: bool


class PayloadClient:
    """The service's HTTP API as two calls, so the rest of the CLI never sees status codes."""

    def __init__(self, http: httpx2.Client) -> None:
        self._http = http

    def create(self, body: Mapping[str, Any]) -> CreatedPayload:
        # Encoded here because json= refuses NaN and lone surrogates, which json.loads accepts:
        # the service answers them with a 422, which the CLI should show.
        response = self._send("POST", "/payload", content=json.dumps(body))
        if response.status_code not in (httpx2.codes.CREATED, httpx2.codes.OK):
            raise ServiceError(_describe_failure(response))
        return CreatedPayload(id=_text_field(response, "id"), created=response.status_code == httpx2.codes.CREATED)

    def get_output(self, payload_id: str) -> str:
        response = self._send("GET", f"/payload/{quote(payload_id, safe='')}")
        if response.status_code != httpx2.codes.OK:
            raise ServiceError(_describe_failure(response))
        return _text_field(response, "output")

    def _send(self, method: str, path: str, content: str | None = None) -> httpx2.Response:
        headers = None if content is None else {"Content-Type": "application/json"}
        try:
            return self._http.request(method, path, content=content, headers=headers)
        except httpx2.RequestError as error:
            raise ServiceError(f"{method} {error.request.url} got no answer: {error}") from error


def _describe_failure(response: httpx2.Response) -> str:
    answer = _describe_answer(response)
    message = _service_message(response)
    return f"{answer}: {message}" if message else answer


def _describe_answer(response: httpx2.Response) -> str:
    request = response.request
    return f"{request.method} {request.url} answered {response.status_code} {response.reason_phrase}"


def _service_message(response: httpx2.Response) -> str:
    """Its own errors carry `message` and FastAPI's carry `detail`; any other body, such as a proxy's page, is cut."""
    match _json_or_none(response):
        case {"message": str(message)}:
            return message
        case {"detail": str(detail)}:
            return detail
        case {"detail": [*errors]}:
            return "; ".join(_describe_validation_error(error) for error in errors)
    text = " ".join(response.text.split())
    return text if len(text) <= _MAX_QUOTED_TEXT else text[:_MAX_QUOTED_TEXT] + "…"


def _describe_validation_error(error: Any) -> str:
    match error:
        case {"loc": [*location], "msg": str(message)}:
            return f"{'.'.join(map(str, location))}: {message}"
    return json.dumps(error)


def _text_field(response: httpx2.Response, name: str) -> str:
    body = _json_or_none(response)
    value = body.get(name) if isinstance(body, dict) else None
    if not isinstance(value, str):
        raise ServiceError(f"{_describe_answer(response)} without a text {name!r} in its body")
    return value


def _json_or_none(response: httpx2.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
