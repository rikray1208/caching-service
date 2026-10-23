import json
import sys
import time
from collections.abc import Mapping
from typing import Any, Final, TextIO

import httpx2
from pydantic import ValidationError

from payload_cache.cli.client import PayloadClient, ServiceError
from payload_cache.cli.settings import PROG_NAME, CliSettings, parse_request_body, parse_settings

EXIT_OK: Final = 0
EXIT_SERVICE_FAILED: Final = 1
EXIT_INVALID_ARGUMENTS: Final = 2  # argparse's status for a usage error, so every invalid argument ends alike


def main() -> None:
    """The cache-cli entry point. Exit status: 0 done, 1 the service failed, 2 invalid arguments."""
    try:
        settings = parse_settings(sys.argv[1:])
    except ValidationError as error:
        for detail in error.errors():
            flag = f"--{detail['loc'][0]}: " if detail["loc"] else ""
            print(f"{PROG_NAME}: error: {flag}{detail['msg']}", file=sys.stderr)
        sys.exit(EXIT_INVALID_ARGUMENTS)

    body = read_request_body(settings)
    # Only the arguments decide how the CLI connects: by default, httpx2 also reads proxy and TLS settings
    # from the environment and the system's proxy settings.
    with httpx2.Client(base_url=str(settings.host), trust_env=False) as http:
        status = run(body, settings.repeat, PayloadClient(http), output=sys.stdout, progress=sys.stderr)
    sys.exit(status)


def read_request_body(settings: CliSettings) -> dict[str, Any]:
    return parse_request_body(settings.json_text)


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
