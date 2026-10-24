import json
import sys
import time
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from io import TextIOWrapper
from pathlib import Path
from typing import Any, Final, NoReturn, TextIO

import httpx2
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.cli.client import PayloadClient, ServiceError
from app.cli.settings import PROG_NAME, CliSettings, StandardStream, parse_request_body, parse_settings

EXIT_OK: Final = 0
EXIT_SERVICE_FAILED: Final = 1
EXIT_INVALID_ARGUMENTS: Final = 2  # argparse's status for a usage error, so every invalid argument ends alike
# JSON is UTF-8 whatever the locale; the -sig variant also accepts the byte order mark that Windows editors write.
_BODY_ENCODING: Final = "utf-8-sig"


def main() -> None:
    """The cache-cli entry point. Exit status: 0 done, 1 the service failed, 2 invalid arguments or input."""
    try:
        settings = parse_settings(sys.argv[1:])
    except ValidationError as error:
        _exit_invalid(*map(_describe_invalid_argument, error.errors()))
    if isinstance(sys.stdin, TextIOWrapper):
        sys.stdin.reconfigure(encoding=_BODY_ENCODING)
    try:
        body = read_request_body(settings, sys.stdin)
    except (OSError, ValueError) as error:
        # --json was checked while the arguments were parsed, so only --input can fail here.
        _exit_invalid(f"--input: {error}")
    # Opened only once the body is read, so that invalid input leaves an existing file as it was.
    try:
        output_file = _open_output(settings.output_path)
    except OSError as error:
        _exit_invalid(f"--output: {error}")

    # Only the arguments decide how the CLI connects: by default, httpx2 also reads proxy and TLS settings
    # from the environment and the system's proxy settings.
    with output_file as output, httpx2.Client(base_url=str(settings.host), trust_env=False) as http:
        status = run(body, settings.repeat, PayloadClient(http), output=output, progress=sys.stderr)
    sys.exit(status)


def _describe_invalid_argument(detail: ErrorDetails) -> str:
    flag = f"--{detail['loc'][0]}: " if detail["loc"] else ""
    match detail:
        # A ValueError from the CLI's own checks reads as its message alone, as the errors of reading --input do.
        case {"type": "value_error", "ctx": {"error": ValueError() as error}}:
            return f"{flag}{error}"
    return f"{flag}{detail['msg']}"


def _exit_invalid(*reasons: str) -> NoReturn:
    for reason in reasons:
        print(f"{PROG_NAME}: error: {reason}", file=sys.stderr)
    sys.exit(EXIT_INVALID_ARGUMENTS)


def read_request_body(settings: CliSettings, stdin: TextIO) -> dict[str, Any]:
    """
    The body from --json, the --input file, or stdin for "-". Raise ValueError unless it is a JSON object,
    and OSError if the file can't be read.
    """
    match settings.input_path:
        case "-":
            text = stdin.read()
        case Path() as path:
            text = path.read_text(encoding=_BODY_ENCODING)
        case None:
            assert settings.json_text is not None, "CliSettings requires --input or --json"
            text = settings.json_text
    return parse_request_body(text)


def _open_output(path: StandardStream | Path) -> AbstractContextManager[TextIO]:
    if isinstance(path, Path):
        return path.open("w", encoding="utf-8")
    return nullcontext(sys.stdout)  # not closed: stdout belongs to whoever runs the CLI


def run(body: Mapping[str, Any], repeat: int, client: PayloadClient, *, output: TextIO, progress: TextIO) -> int:
    """
    Send the body `repeat` times, one POST and one GET per round. Write {"id", "created", "output"} as a JSON line
    per round to `output`, and the round's time to `progress`. Stop at the first ServiceError and return 1: the CLI
    shows how the service behaves, so it doesn't retry.
    """
    for round_number in range(1, repeat + 1):
        started = time.perf_counter()
        try:
            created = client.create(body)
            payload_output = client.get_output(created.id)
        except ServiceError as error:
            print(f"Round {round_number} of {repeat} failed: {error}", file=progress)
            return EXIT_SERVICE_FAILED
        elapsed = time.perf_counter() - started

        line = {"id": created.id, "created": created.created, "output": payload_output}
        print(json.dumps(line), file=output, flush=True)
        print(f"Round {round_number} of {repeat}: {elapsed:.3f} s", file=progress)
    return EXIT_OK
