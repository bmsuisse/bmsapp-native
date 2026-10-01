import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from server import create_app

PACKAGE = Path(__file__).resolve().parent.parent / "packages" / "app-native"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    # A fixed time zone, so the date helpers give the same result on every machine.
    return {**browser_context_args, "timezone_id": "Europe/Zurich"}


@pytest.fixture(scope="session", autouse=True)
def _build_package() -> None:
    # Tests run against the built package (dist/), exactly what gets published.
    subprocess.run(["bun", "run", "build"], cwd=PACKAGE, check=True)


@pytest.fixture(scope="session")
def base_url(_build_package: None) -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
