"""Start the real application for browser tests and wait for /healthz."""

import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def base_url() -> str:
    port = _free_port()
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("application exited before it became healthy")
        try:
            with urlopen(f"{url}/healthz", timeout=1) as response:  # noqa: S310 - fixed localhost
                if response.status == 200:
                    break
        except (URLError, ConnectionError, TimeoutError):
            time.sleep(0.2)
    else:
        process.terminate()
        raise RuntimeError("application did not become healthy in time")

    yield url
    process.terminate()
    process.wait(timeout=10)
