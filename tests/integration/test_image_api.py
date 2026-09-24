"""POST /api/ai/describe-image, from docs/test_plan.md §4 and §7.

Every case uses a fake provider: no test makes a paid call.
"""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, get_ai_provider
from app.services import ai_extraction
from app.services.ai_extraction import AIError, FakeProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64

VALID_BODY = json.dumps(
    {
        "alt_text": "Bar chart of weekly sign-ups, highest in week 4.",
        "caption": "Sign-ups peaked at 212 in week 4.",
        "review_notes": ["The y-axis label is too small to read."],
    }
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_limits():
    ai_extraction.limiter = ai_extraction.RateLimiter()
    yield
    app.dependency_overrides.clear()
    settings.ai_enabled = False


def data_url(data: bytes, kind: str = "png") -> str:
    return f"data:image/{kind};base64," + base64.b64encode(data).decode()


class Recording:
    """A provider that records what it was sent."""

    def __init__(self, body: str = VALID_BODY) -> None:
        self.body = body
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt: str, source_text: str) -> str:
        return VALID_BODY_TEXT

    def describe_image(self, prompt: str, image_data_url: str) -> str:
        self.calls.append((prompt, image_data_url))
        return self.body


VALID_BODY_TEXT = json.dumps(
    {
        "title": "Update",
        "summary": "Done.",
        "completed_items": [],
        "next_steps": [],
        "risks": [],
        "review_notes": [],
    }
)


def use(provider):
    settings.ai_enabled = True
    app.dependency_overrides[get_ai_provider] = lambda: provider
    return provider


def post(url: str):
    return client.post("/api/ai/describe-image", json={"image_data_url": url})


def test_an_image_produces_a_draft_and_review_notes():
    use(FakeProvider(body=VALID_BODY))
    response = post(data_url(PNG))
    assert response.status_code == 200
    body = response.json()
    assert body["draft"]["alt_text"].startswith("Bar chart")
    assert body["draft"]["caption"] == "Sign-ups peaked at 212 in week 4."
    assert body["review_notes"] == ["The y-axis label is too small to read."]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("data", "kind"), [(PNG, "png"), (JPEG, "jpeg"), (WEBP, "webp")])
def test_each_accepted_type_reaches_the_provider_with_the_image_prompt(data, kind):
    provider = use(Recording())
    assert post(data_url(data, kind)).status_code == 200
    prompt, sent = provider.calls[0]
    assert sent == data_url(data, kind)
    assert "Never calculate" in prompt  # the image prompt, not the notes prompt


def test_ai_disabled_returns_503():
    settings.ai_enabled = False
    assert post(data_url(PNG)).status_code == 503


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/chart.png",  # a remote URL is never fetched
        "data:image/gif;base64," + base64.b64encode(b"GIF89a").decode(),
        "data:image/png;base64,not base64!",
        data_url(JPEG, "png"),  # declares PNG, contains JPEG
        data_url(b"RIFF\x00\x00\x00\x00AVI " + b"\x00" * 8, "webp"),
        "",
    ],
)
def test_anything_but_a_real_image_is_refused_before_the_provider_is_called(url):
    provider = use(Recording())
    response = post(url)
    assert response.status_code == 422
    assert provider.calls == []


def test_a_refused_image_is_not_echoed_back():
    use(Recording())
    url = data_url(JPEG, "png")
    body = post(url).text
    assert base64.b64encode(JPEG).decode()[:24] not in body
    assert "image_data_url" in body  # the field is named, the value is not


def test_extra_fields_are_rejected():
    use(Recording())
    response = client.post(
        "/api/ai/describe-image", json={"image_data_url": data_url(PNG), "prompt": "x"}
    )
    assert response.status_code == 422


def test_an_image_over_1_mib_is_refused():
    use(Recording())
    big = PNG + b"\x00" * (1024 * 1024)
    assert post(data_url(big)).status_code == 422


def test_the_image_route_allows_a_larger_body_but_not_an_unbounded_one():
    use(Recording())
    padding = "A" * (1600 * 1024)
    response = client.post(
        "/api/ai/describe-image",
        content=json.dumps({"image_data_url": "data:image/png;base64," + padding}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_other_routes_keep_the_64_kib_limit():
    response = client.post(
        "/api/cards/render",
        content="x" * (100 * 1024),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_long_alt_text_from_the_model_is_kept_for_the_person_to_trim():
    # The live model returned ~570 characters when asked for fewer than 300.
    body = json.dumps({"alt_text": "A" * 570, "caption": "", "review_notes": []})
    use(FakeProvider(body=body))
    response = post(data_url(PNG))
    assert response.status_code == 200
    assert len(response.json()["draft"]["alt_text"]) == 570


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps(["a list"]),
        json.dumps({"alt_text": "", "caption": "", "review_notes": []}),
        json.dumps({"alt_text": "A" * 1001, "caption": "", "review_notes": []}),
        json.dumps({"alt_text": "ok", "caption": "", "review_notes": [], "status": "done"}),
    ],
)
def test_a_malformed_answer_is_a_502_and_never_echoed(raw):
    use(FakeProvider(body=raw))
    response = post(data_url(PNG))
    assert response.status_code == 502
    assert raw[:20] not in response.text


def test_timeout_is_a_504_that_says_the_card_is_unchanged():
    use(FakeProvider(body="", raises=TimeoutError()))
    response = post(data_url(PNG))
    assert response.status_code == 504
    assert "card is unchanged" in response.json()["error"]["message"]


def test_a_content_filter_refusal_is_passed_through_as_422():
    use(FakeProvider(body="", raises=AIError(422, "The content filter rejected this image.")))
    assert post(data_url(PNG)).status_code == 422


def test_text_and_image_requests_share_one_rate_limit():
    use(Recording())
    for _ in range(ai_extraction.MAX_CALLS_PER_MINUTE):
        assert (
            client.post("/api/ai/extract-progress", json={"source_text": "notes"}).status_code
            == 200
        )
    assert post(data_url(PNG)).status_code == 429
