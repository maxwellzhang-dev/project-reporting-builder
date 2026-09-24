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


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "rich_clipboard: the test writes the email HTML to the clipboard, which makes "
        "Chromium report its inline styles against the page's CSP",
    )


@pytest.fixture(autouse=True)
def _no_csp_violations(page, request):
    """Every browser test doubles as a Content-Security-Policy check: any
    resource or script the policy blocks fails the test that triggered it
    (docs/architecture.md §12). Chromium reports each violation to the
    console, which survives reloads, unlike an in-page listener.

    One known report is tolerated, and only in tests marked rich_clipboard:
    writing the email HTML to the clipboard makes Chromium parse it in the
    page and report every style="" attribute, although the attributes reach
    the clipboard intact (the test asserts they do). The page itself never
    renders that HTML, so style-src stays 'self' rather than being loosened
    for a report that changes nothing."""
    violations = []
    page.on(
        "console",
        lambda message: violations.append(message.text)
        if "Content Security Policy" in message.text
        else None,
    )
    yield
    if request.node.get_closest_marker("rich_clipboard"):
        violations = [text for text in violations if "Applying inline style" not in text]
    assert not violations, f"CSP blocked something: {violations}"
