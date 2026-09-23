"""The two endpoints this milestone implements, plus their static assets."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_index_serves_the_editor_shell():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'data-add-card="progress"' in response.text
    assert 'id="card-list"' in response.text
    assert 'id="confirm-delete"' in response.text


def test_index_links_its_local_assets():
    body = client.get("/").text
    assert "/static/css/app.css" in body
    assert "/static/js/main.js" in body
    assert "cdn" not in body.lower()


def test_static_assets_are_served():
    for path, expected in (
        ("/static/css/app.css", "--status-in-progress"),
        ("/static/js/main.js", "healthz"),
        ("/static/js/theme.js", "prefers-color-scheme"),
        # Vendored, not fetched from a CDN (docs/architecture.md §1).
        ("/static/vendor/basecoat/basecoat.min.css", ".btn"),
        ("/static/vendor/lucide/icons.svg", 'id="sparkles"'),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert expected in response.text


def test_page_has_one_h1_and_a_skip_link():
    body = client.get("/").text
    assert body.count("<h1>") == 1
    assert 'class="skip-link"' in body
