"""Hardening against a hostile client, from docs/architecture.md §12.

The site is public, has no login and pays per AI call, so the realistic
attacks are exhausting memory, the AI budget or other people's access, and
injecting script. Each test here names the attack it stands in for.
"""

import json
import select
import socket
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import CONTENT_SECURITY_POLICY, app, get_ai_provider
from app.services import ai_extraction
from app.services.ai_extraction import FakeProvider

CHUNK = 64 * 1024
STREAM = 10 * 1024 * 1024


@pytest.fixture(scope="module")
def live_server():
    """A real uvicorn process. TestClient reads the whole request body before
    the app sees any of it, so it cannot show whether the server stops
    reading early; only a real socket can."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
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
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    yield port
    process.terminate()
    process.wait(timeout=10)


def stream_until_answered(port: int, path: str) -> tuple[int, bytes]:
    """Send a chunked body of up to 10 MiB with no Content-Length, stopping as
    soon as the server answers. Returns (bytes sent, first line of the reply)."""
    sent = 0
    with socket.create_connection(("127.0.0.1", port), timeout=10) as conn:
        conn.sendall(
            f"POST {path} HTTP/1.1\r\nHost: localhost\r\n"
            "Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n".encode()
        )
        chunk = f"{CHUNK:x}\r\n".encode() + b"x" * CHUNK + b"\r\n"
        while sent < STREAM:
            readable, _, _ = select.select([conn], [], [], 0)
            if readable:
                break
            try:
                conn.sendall(chunk)
            except OSError:
                break  # the server closed the connection on us: also a refusal
            sent += CHUNK
        conn.settimeout(10)
        reply = conn.recv(64)
    return sent, reply.split(b"\r\n", 1)[0]


def test_a_chunked_body_with_no_length_is_cut_off_early_not_read_whole(live_server):
    """Attack: stream an endless body without Content-Length to fill memory.
    The limit has to be enforced while reading; measuring after reading
    everything is exactly what the attacker wants."""
    sent, status = stream_until_answered(live_server, "/api/cards/render")
    assert b"413" in status
    # The server stops at 64 KiB; the rest is what the operating system's
    # socket buffers had already taken (about 1.2 MiB measured on macOS). The
    # old code never answered at all: it read all 10 MiB and kept waiting.
    assert sent < 3 * 1024 * 1024, f"server accepted {sent} bytes before refusing"


def test_the_image_routes_stop_reading_at_their_own_larger_limit(live_server):
    sent, status = stream_until_answered(live_server, "/api/ai/extract-progress")
    assert b"413" in status
    assert sent < 7 * 1024 * 1024, f"server accepted {sent} bytes before refusing"


# ---- response headers ----------------------------------------------------------

client = TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/", None),
        ("GET", "/healthz", None),
        ("GET", "/static/js/main.js", None),
        ("GET", "/no-such-page", None),  # errors carry them too
        ("POST", "/api/cards/render", "x" * (70 * 1024)),  # the 413 from BodySizeLimit
    ],
)
def test_every_response_carries_the_security_headers(method, path, body):
    response = client.request(method, path, content=body)
    headers = response.headers
    assert headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"  # attack: framing the page for clickjacking
    assert headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" in headers


def test_the_policy_allows_no_inline_script_and_no_other_origin():
    """Attack: an injected <script> or a script from another site. Only files
    served from this origin run."""
    directives = dict(part.split(" ", 1) for part in CONTENT_SECURITY_POLICY.split("; "))
    assert directives["script-src"] == "'self'"
    assert directives["frame-ancestors"] == "'none'"
    assert directives["object-src"] == "'none'"
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY


# ---- rate limiting per client --------------------------------------------------

DRAFT = json.dumps(
    {"title": "T", "summary": "S", "completed_items": [], "next_steps": [], "risks": []}
)


@pytest.fixture
def ai_on():
    ai_extraction.limiter = ai_extraction.RateLimiter()
    settings.ai_enabled = True
    app.dependency_overrides[get_ai_provider] = lambda: FakeProvider(body=DRAFT)
    yield
    app.dependency_overrides.clear()
    settings.ai_enabled = False
    settings.trusted_proxy_hops = 0
    ai_extraction.limiter = ai_extraction.RateLimiter()


def draft_as(forwarded: str | None = None):
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    return client.post("/api/ai/extract-progress", json={"source_text": "n"}, headers=headers)


def test_one_client_using_up_its_limit_does_not_lock_out_another(ai_on):
    """Attack: one person spams the AI endpoint so nobody else can use it."""
    settings.trusted_proxy_hops = 1
    for _ in range(ai_extraction.MAX_CALLS_PER_MINUTE):
        assert draft_as("203.0.113.7").status_code == 200
    assert draft_as("203.0.113.7").status_code == 429
    assert draft_as("198.51.100.9").status_code == 200


def test_a_forged_forwarded_header_does_not_buy_a_fresh_limit(ai_on):
    """Attack: rotate a fake X-Forwarded-For to look like many people. The
    proxy appends the real address on the right; only that entry counts."""
    settings.trusted_proxy_hops = 1
    for fake in range(ai_extraction.MAX_CALLS_PER_MINUTE):
        assert draft_as(f"10.0.0.{fake}, 203.0.113.7").status_code == 200
    assert draft_as("10.9.9.9, 203.0.113.7").status_code == 429


def test_without_a_trusted_proxy_the_header_is_ignored(ai_on):
    """Run directly (locally) there is no proxy, so the header is whatever the
    client chose and must not identify it."""
    settings.trusted_proxy_hops = 0
    for fake in range(ai_extraction.MAX_CALLS_PER_MINUTE):
        assert draft_as(f"10.0.0.{fake}").status_code == 200
    assert draft_as("10.0.0.99").status_code == 429


def test_many_clients_together_still_hit_a_total_ceiling(ai_on):
    """Attack: spread requests over many real addresses. The total cap is
    what bounds the Azure bill however many addresses there are."""
    settings.trusted_proxy_hops = 1
    ai_extraction.limiter = ai_extraction.RateLimiter(max_per_minute=6, max_total_per_minute=8)
    for address in range(8):
        assert draft_as(f"198.51.100.{address}").status_code == 200
    response = draft_as("198.51.100.200")
    assert response.status_code == 429
    assert "busy" in response.json()["error"]["message"]


def test_head_requests_are_answered_like_get():
    """Uptime monitors and link checkers often send HEAD. Starlette 1.x no
    longer adds it to GET routes by itself; this caught the regression."""
    for path in ("/", "/healthz"):
        response = client.head(path)
        assert response.status_code == 200, path
        assert response.headers["x-content-type-options"] == "nosniff"


def test_static_files_are_revalidated_so_a_deploy_is_never_half_applied():
    client = TestClient(app)
    response = client.get("/static/js/main.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    again = client.get("/static/js/main.js", headers={"If-None-Match": response.headers["etag"]})
    assert again.status_code == 304
