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

MAX_CALLS_PER_MINUTE = 6
MAX_CONCURRENT = 1
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
    """In-process limiter. Resets on restart and does not span replicas —
    acceptable for a single-replica POC, and documented as such."""

    def __init__(self, max_per_minute: int = MAX_CALLS_PER_MINUTE) -> None:
        self.max_per_minute = max_per_minute
        self._calls: list[float] = []
        self._in_flight = 0

    def acquire(self) -> None:
        now = time.monotonic()
        self._calls = [stamp for stamp in self._calls if now - stamp < 60]
        if len(self._calls) >= self.max_per_minute:
            raise AIError(429, "Too many AI requests. Wait a moment and try again.")
        if self._in_flight >= MAX_CONCURRENT:
            raise AIError(429, "Another AI request is still running.")
        self._calls.append(now)
        self._in_flight += 1

    def release(self) -> None:
        self._in_flight = max(0, self._in_flight - 1)


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


def _call(provider: Provider | None, send: Callable[[Provider], str], unchanged: str) -> str:
    """One provider call under the shared limiter, with the documented error
    mapping. Text and image requests share both, so neither can be used to get
    around the other's rate limit."""
    if not settings.ai_enabled or provider is None:
        raise AIError(503, "AI assistance is turned off.")

    limiter.acquire()
    try:
        return send(provider)
    except AIError:
        raise
    except TimeoutError as error:
        raise AIError(504, f"The model took too long. {unchanged}") from error
    except Exception as error:  # provider failures must not leak their detail
        raise AIError(502, "The model could not be reached.") from error
    finally:
        limiter.release()


def extract_progress(
    source_text: str, provider: Provider | None, image_data_url: str | None = None
) -> ExtractResponse:
    def send(live: Provider) -> str:
        if image_data_url is None:
            return live.complete(load_prompt(), source_text)
        return live.complete(load_prompt(), source_text, image_data_url=image_data_url)

    raw = _call(provider, send, "Your notes are unchanged.")
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


def describe_image(image_data_url: str, provider: Provider | None) -> DescribeImageResponse:
    """Draft alt text and a caption for one image. Nothing is applied to a
    card here: the person reviews the draft and chooses to use it (scope §5)."""
    prompt = IMAGE_PROMPT_PATH.read_text(encoding="utf-8")
    raw = _call(
        provider,
        lambda live: live.describe_image(prompt, image_data_url),
        "Your card is unchanged.",
    )
    return _parse_image(raw)
