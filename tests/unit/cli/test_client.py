import httpx2
import pytest

from payload_cache.cli.client import CreatedPayload, ServiceError
from tests.doubles import payload_client_for

BODY = {"list_1": ["a"], "list_2": ["b"]}


@pytest.mark.parametrize(("status_code", "created"), [(201, True), (200, False)])
def test_create_posts_the_body_and_reports_whether_the_payload_is_new(status_code: int, created: bool) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(status_code, json={"id": "payload-1", "message": "…"})

    assert payload_client_for(handler).create(BODY) == CreatedPayload(id="payload-1", created=created)
    [request] = requests
    assert (request.method, request.url) == ("POST", "http://service.test/payload")
    assert request.headers["Content-Type"] == "application/json"
    assert request.content == b'{"list_1": ["a"], "list_2": ["b"]}'


def test_create_sends_bodies_that_the_service_must_reject() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(422, json={"detail": []})

    with pytest.raises(ServiceError):
        payload_client_for(handler).create({"list_1": ["\ud800"], "list_2": [float("nan")]})

    assert requests[0].content == b'{"list_1": ["\\ud800"], "list_2": [NaN]}'


def test_get_output_reads_the_payload() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"output": "A, B"})

    assert payload_client_for(handler).get_output("payload-1") == "A, B"
    assert [(request.method, request.url) for request in requests] == [("GET", "http://service.test/payload/payload-1")]


def test_get_output_keeps_the_id_in_one_path_segment() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"output": "A, B"})

    payload_client_for(handler).get_output("../other?x=1")

    assert [request.url.raw_path for request in requests] == [b"/payload/..%2Fother%3Fx%3D1"]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        pytest.param(
            httpx2.Response(
                422,
                json={
                    "code": "unequal_lists",
                    "message": "list_1 and list_2 must have the same length.",
                    "details": {"list_1_length": 2, "list_2_length": 1},
                },
            ),
            "POST http://service.test/payload answered 422 Unprocessable Content: "
            "list_1 and list_2 must have the same length.",
            id="the service's error",
        ),
        pytest.param(
            httpx2.Response(
                422,
                json={
                    "detail": [
                        {
                            "type": "too_short",
                            "loc": ["body", "list_1"],
                            "msg": "List should have at least 1 item after validation, not 0",
                            "input": [],
                        },
                        {"type": "missing", "loc": ["body", "list_2"], "msg": "Field required", "input": {}},
                    ]
                },
            ),
            "POST http://service.test/payload answered 422 Unprocessable Content: "
            "body.list_1: List should have at least 1 item after validation, not 0; body.list_2: Field required",
            id="FastAPI's validation errors",
        ),
        pytest.param(
            httpx2.Response(404, json={"detail": "Not Found"}),
            "POST http://service.test/payload answered 404 Not Found: Not Found",
            id="FastAPI's HTTP error",
        ),
        pytest.param(
            httpx2.Response(502, text="<html>\r\n<body>\r\n<h1>502 Bad Gateway</h1>\r\n</body>\r\n</html>"),
            "POST http://service.test/payload answered 502 Bad Gateway: "
            "<html> <body> <h1>502 Bad Gateway</h1> </body> </html>",
            id="not JSON",
        ),
        pytest.param(
            httpx2.Response(500, text="x" * 301),
            f"POST http://service.test/payload answered 500 Internal Server Error: {'x' * 300}…",
            id="cut after 300 characters",
        ),
        pytest.param(
            httpx2.Response(422, json={"code": "c", "message": "m" * 301, "details": None}),
            f"POST http://service.test/payload answered 422 Unprocessable Content: {'m' * 301}",
            id="the service's message in full",
        ),
        pytest.param(
            httpx2.Response(503),
            "POST http://service.test/payload answered 503 Service Unavailable",
            id="no body",
        ),
        pytest.param(
            httpx2.Response(201, text="<html>Welcome</html>"),
            "POST http://service.test/payload answered 201 Created without a text 'id' in its body",
            id="success without an id",
        ),
    ],
)
def test_create_quotes_the_service_when_it_fails(response: httpx2.Response, message: str) -> None:
    with pytest.raises(ServiceError) as exc_info:
        payload_client_for(lambda request: response).create(BODY)

    assert str(exc_info.value) == message


def test_get_output_quotes_the_service_when_it_fails() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = {"code": "payload_not_found", "message": "Payload not found.", "details": {"payload_id": "x"}}
        return httpx2.Response(404, json=body)

    with pytest.raises(ServiceError) as exc_info:
        payload_client_for(handler).get_output("x")

    assert str(exc_info.value) == "GET http://service.test/payload/x answered 404 Not Found: Payload not found."


def test_a_network_error_is_a_service_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("All connection attempts failed")

    with pytest.raises(ServiceError) as exc_info:
        payload_client_for(handler).create(BODY)

    assert str(exc_info.value) == "POST http://service.test/payload got no answer: All connection attempts failed"
