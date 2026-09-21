"""Start the application for browser tests and wait for /healthz.

It is started through `tests.e2e.ai_app`, which is the real application with
the AI provider replaced by a scripted fake. No browser test can reach Azure,
and none costs money, even on a machine whose `.env` holds real credentials.
"""

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
            "tests.e2e.ai_app:app",
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
