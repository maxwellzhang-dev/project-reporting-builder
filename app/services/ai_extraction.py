"""Turn source notes into a progress draft, and an image into a description,
or fail in a documented way.

The provider is an interface so tests and CI never make a paid call
(docs/test_plan.md §1). Error mapping follows docs/architecture.md §6.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from app.config import settings
from app.schemas.ai import DescribeImageResponse, ExtractResponse, ImageDraft, ProgressDraft

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
PROMPT_PATH = PROMPTS_DIR / "extract_progress_v3.txt"
PROMPT_VERSION = "extract_progress_v3"
IMAGE_PROMPT_PATH = PROMPTS_DIR / "describe_image_v1.txt"
IMAGE_PROMPT_VERSION = "describe_image_v1"

# Per client, so one visitor cannot use up everyone's access...
MAX_CALLS_PER_MINUTE = 6
MAX_CONCURRENT = 1
# ...and in total, which is what bounds the Azure bill however many
# addresses the requests come from.
MAX_CALLS_PER_MINUTE_TOTAL = 30
MAX_CONCURRENT_TOTAL = 3
REQUEST_TIMEOUT_SECONDS = 30


class AIError(Exception):
    """Carries the status code the API should return."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Provider(Protocol):
    # image_data_url is passed only when there is one, so a provider written
    # for text alone keeps working for text.
    def complete(self, prompt: str, source_text: str, image_data_url: str | None = None) -> str: ...

    def describe_image(self, prompt: str, image_data_url: str) -> str: ...


@dataclass
class FakeProvider:
    """Returns a canned body. Used by tests and by CI."""

    body: str
    delay_seconds: float = 0.0
    raises: Exception | None = None

    def complete(self, prompt: str, source_text: str, image_data_url: str | None = None) -> str:
        if self.raises is not None:
            raise self.raises
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return self.body

    def describe_image(self, prompt: str, image_data_url: str) -> str:
        return self.complete(prompt, image_data_url)


class RateLimiter:
    """In-process limiter, per client and in total. Resets on restart and does
    not span replicas: acceptable for a single-replica POC, and documented as
    such.

    The first version counted every request against one shared budget, so a
    single person sending six requests a minute locked everyone else out.
    """

    def __init__(
        self,
        max_per_minute: int = MAX_CALLS_PER_MINUTE,
        max_total_per_minute: int | None = None,
    ) -> None:
        self.max_per_minute = max_per_minute
        # Never below the per-client figure, so raising that (as the browser
        # tests do) cannot be undercut by the total.
        self.max_total_per_minute = max(
            max_total_per_minute or MAX_CALLS_PER_MINUTE_TOTAL, max_per_minute
        )
        self._calls: dict[str, list[float]] = {}
        self._in_flight: dict[str, int] = {}

    def acquire(self, client: str = "anonymous") -> None:
        now = time.monotonic()
        # Forget clients with nothing in the last minute, so the table cannot
        # grow without bound under a flood of addresses.
        self._calls = {
            key: recent
            for key, stamps in self._calls.items()
            if (recent := [stamp for stamp in stamps if now - stamp < 60])
        }
        total = sum(len(stamps) for stamps in self._calls.values())
        mine = self._calls.get(client, [])
        busy_total = sum(self._in_flight.values())

        if total >= self.max_total_per_minute or busy_total >= max(
            MAX_CONCURRENT_TOTAL, MAX_CONCURRENT
        ):
            raise AIError(429, "The AI service is busy. Try again in a minute.")
        if len(mine) >= self.max_per_minute:
            raise AIError(429, "Too many AI requests. Wait a moment and try again.")
        if self._in_flight.get(client, 0) >= MAX_CONCURRENT:
            raise AIError(429, "Another AI request is still running.")
        self._calls[client] = [*mine, now]
        self._in_flight[client] = self._in_flight.get(client, 0) + 1

    def release(self, client: str = "anonymous") -> None:
        left = self._in_flight.get(client, 0) - 1
        if left > 0:
            self._in_flight[client] = left
        else:
            self._in_flight.pop(client, None)


limiter = RateLimiter()


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _parse(raw: str) -> ExtractResponse:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AIError(502, "The model returned something unreadable.") from error
    if not isinstance(payload, dict):
        raise AIError(502, "The model returned something unreadable.")

    # Lifted out before the draft is validated: ProgressDraft forbids extra
    # fields, and these two belong to the response, not to the progress card.
    notes = payload.pop("review_notes", [])
    metrics = payload.pop("metrics", [])
    try:
        draft = ProgressDraft.model_validate(payload)
        return ExtractResponse(draft=draft, metrics=metrics, review_notes=notes)
    except ValidationError as error:
        # The provider's raw body never reaches the caller (architecture §6).
        raise AIError(502, "The model's answer did not match the expected shape.") from error


def _call(
    provider: Provider | None,
    send: Callable[[Provider], str],
    unchanged: str,
    client: str = "anonymous",
) -> str:
    """One provider call under the shared limiter, with the documented error
    mapping. Text and image requests share both, so neither can be used to get
    around the other's rate limit."""
    if not settings.ai_enabled or provider is None:
        raise AIError(503, "AI assistance is turned off.")

    limiter.acquire(client)
    try:
        return send(provider)
    except AIError:
        raise
    except TimeoutError as error:
        raise AIError(504, f"The model took too long. {unchanged}") from error
    except Exception as error:  # provider failures must not leak their detail
        raise AIError(502, "The model could not be reached.") from error
    finally:
        limiter.release(client)


def extract_progress(
    source_text: str,
    provider: Provider | None,
    image_data_url: str | None = None,
    client: str = "anonymous",
) -> ExtractResponse:
    def send(live: Provider) -> str:
        if image_data_url is None:
            return live.complete(load_prompt(), source_text)
        return live.complete(load_prompt(), source_text, image_data_url=image_data_url)

    raw = _call(provider, send, "Your notes are unchanged.", client)
    return _parse(raw)


def _parse_image(raw: str) -> DescribeImageResponse:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AIError(502, "The model returned something unreadable.") from error
    if not isinstance(payload, dict):
        raise AIError(502, "The model returned something unreadable.")

    notes = payload.pop("review_notes", [])
    try:
        draft = ImageDraft.model_validate(payload)
        return DescribeImageResponse(draft=draft, review_notes=notes)
    except ValidationError as error:
        raise AIError(502, "The model's answer did not match the expected shape.") from error


def describe_image(
    image_data_url: str, provider: Provider | None, client: str = "anonymous"
) -> DescribeImageResponse:
    """Draft alt text and a caption for one image. Nothing is applied to a
    card here: the person reviews the draft and chooses to use it (scope §5)."""
    prompt = IMAGE_PROMPT_PATH.read_text(encoding="utf-8")
    raw = _call(
        provider,
        lambda live: live.describe_image(prompt, image_data_url),
        "Your card is unchanged.",
        client,
    )
    return _parse_image(raw)
