"""POST /api/cards/render, from the table in docs/test_plan.md §4."""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
ID = str(uuid.uuid4())


def render(card: dict, revision: int = 3):
    return client.post("/api/cards/render", json={"revision": revision, "card": card})


METRIC = {
    "id": ID,
    "type": "metric",
    "title": "Completion rate",
    "current": 78,
    "previous": 65,
    "unit": "percent",
    "unit_label": "",
    "note": "",
}
PROGRESS = {
    "id": ID,
    "type": "progress",
    "title": "Payments migration",
    "status": "in_progress",
    "summary": "Twelve of eighteen accounts moved.",
    "completed": ["Dual-write enabled"],
    "next_steps": [],
    "risks": ["Vendor date unknown"],
}
IMAGE = {
    "id": ID,
    "type": "image",
    "title": "Burndown",
    "alt_text": "Burndown chart trending down",
    "caption": "Week 38",
}


def test_valid_request_echoes_id_and_revision_with_all_outputs():
    body = render(METRIC).json()
    assert body["card_id"] == ID
    assert body["revision"] == 3
    assert body["preview_html"] and body["plain_text"] and body["rich_html"]


def test_percentage_metric_shows_points_and_relative_change():
    body = render(METRIC).json()
    text = body["plain_text"]
    assert "78%" in text
    assert "+13 percentage points" in text
    assert "+20% relative change" in text


def test_progress_card_omits_empty_sections():
    text = render(PROGRESS).json()["plain_text"]
    assert "Completed" in text and "Risks" in text
    assert "Next steps" not in text


def test_image_card_returns_metadata_preview_and_no_rich_html():
    body = render(IMAGE).json()
    assert body["rich_html"] is None
    assert "Burndown chart trending down" in body["preview_html"]
    assert "Week 38" in body["preview_html"]


def test_invalid_fields_return_422_with_field_paths():
    response = render({**METRIC, "current": "seventy-eight"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(field["path"].endswith("current") for field in error["fields"])


def test_errors_do_not_echo_the_submitted_value():
    """architecture §6: never expose raw Pydantic input."""
    response = render({**METRIC, "current": "seventy-eight"})
    assert "seventy-eight" not in response.text


def test_malformed_json_is_a_controlled_error():
    response = client.post(
        "/api/cards/render", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


def test_request_over_64_kib_returns_413():
    oversized = {**PROGRESS, "summary": "x" * 70_000}
    assert render(oversized).status_code == 413


def test_template_payloads_are_escaped_not_executed():
    body = render(
        {**PROGRESS, "title": "<script>alert(1)</script>", "summary": "{{ 7 * 7 }}"}
    ).json()
    assert "<script>" not in body["preview_html"]
    assert "49" not in body["preview_html"]


def test_render_response_is_not_cached():
    assert render(METRIC).headers["cache-control"] == "no-store"


def test_zero_baseline_reports_no_relative_change():
    text = render({**METRIC, "current": 10, "previous": 0, "unit": "number"}).json()["plain_text"]
    assert "relative change" not in text.lower()
    assert "+10" in text


def test_missing_previous_value_renders_only_the_current_value():
    text = render({**METRIC, "previous": None}).json()["plain_text"]
    assert "78%" in text
    assert "percentage points" not in text
