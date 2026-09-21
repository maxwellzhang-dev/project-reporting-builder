"""Turn source notes into a progress draft, or fail in a documented way.

The provider is an interface so tests and CI never make a paid call
(docs/test_plan.md §1). Error mapping follows docs/architecture.md §6.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from app.config import settings
from app.schemas.ai import ExtractResponse, ProgressDraft

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract_progress_v1.txt"
PROMPT_VERSION = "extract_progress_v1"

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
    def complete(self, prompt: str, source_text: str) -> str: ...


@dataclass
class FakeProvider:
    """Returns a canned body. Used by tests and by CI."""

    body: str
    delay_seconds: float = 0.0
    raises: Exception | None = None

    def complete(self, prompt: str, source_text: str) -> str:
        if self.raises is not None:
            raise self.raises
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return self.body


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

    notes = payload.pop("review_notes", [])
    try:
        draft = ProgressDraft.model_validate(payload)
        return ExtractResponse(draft=draft, review_notes=notes)
    except ValidationError as error:
        # The provider's raw body never reaches the caller (architecture §6).
        raise AIError(502, "The model's answer did not match the expected shape.") from error


def extract_progress(source_text: str, provider: Provider | None) -> ExtractResponse:
    if not settings.ai_enabled or provider is None:
        raise AIError(503, "AI assistance is turned off.")

    limiter.acquire()
    try:
        raw = provider.complete(load_prompt(), source_text)
    except AIError:
        raise
    except TimeoutError as error:
        raise AIError(504, "The model took too long. Your text is unchanged.") from error
    except Exception as error:  # provider failures must not leak their detail
        raise AIError(502, "The model could not be reached.") from error
    finally:
        limiter.release()

    return _parse(raw)
