import logging
import socket
import time
from collections.abc import Iterator

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.core.run import create_app
from app.core.settings import Settings
from app.health.router import PROBE_TIMEOUT_SECONDS

# The apps on an unavailable database are built in fixtures, not in the test bodies,
# so that create_app's logging setup runs before caplog adds its handler.


@pytest.fixture
def refusing_database_client(app_settings: Settings) -> Iterator[TestClient]:
    # Freed again at once, so that it refuses connections. A port kept bound without listening would refuse
    # on Linux, but macOS drops the connection attempt instead.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]

    with _client_on_local_port(app_settings, closed_port) as client:
        yield client


@pytest.fixture
def silent_database_client(app_settings: Settings) -> Iterator[TestClient]:
    with socket.socket() as sock:
        # The kernel completes the TCP handshake, but nothing accepts, so the database never answers.
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        with _client_on_local_port(app_settings, sock.getsockname()[1]) as client:
            yield client


def _client_on_local_port(app_settings: Settings, port: int) -> TestClient:
    database = app_settings.database.model_copy(update={"host": "127.0.0.1", "port": port})
    return TestClient(create_app(app_settings.model_copy(update={"database": database})))


def _assert_unavailable_and_warned(
    response: httpx2.Response, caplog: pytest.LogCaptureFixture, error_name: str
) -> None:
    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "unavailable"}
    [warning] = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert warning.levelno == logging.WARNING
    assert error_name in warning.getMessage()
    assert warning.exc_info is None


def test_health_answers_200_when_the_database_answers(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_health_answers_503_and_warns_without_a_traceback_when_the_database_refuses(
    refusing_database_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = refusing_database_client.get("/health")

    _assert_unavailable_and_warned(response, caplog, "ConnectionRefusedError")


def test_health_answers_503_after_its_timeout_when_the_database_never_answers(
    silent_database_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    started = time.monotonic()
    response = silent_database_client.get("/health")
    elapsed = time.monotonic() - started

    _assert_unavailable_and_warned(response, caplog, "TimeoutError")
    assert PROBE_TIMEOUT_SECONDS <= elapsed < PROBE_TIMEOUT_SECONDS + 1
