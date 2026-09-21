"""The application as the browser tests see it: AI on, provider fake.

Browser tests need the AI endpoint to answer, but a paid call from a test is
never acceptable (docs/test_plan.md §1) and a developer's own `.env` may hold
real credentials. This module overrides the provider dependency, so the real
one is never constructed here whatever `.env` says, and forces `ai_enabled` on
so the tests behave the same on a machine with credentials and on CI without
any.

The fake decides what to do from markers in the source text, which lets a
browser test drive success, slowness and each failure from the page itself.
"""

import json
import time

from app.config import settings
from app.main import app, get_ai_provider
from app.services import ai_extraction
from app.services.ai_extraction import AIError

settings.ai_enabled = True

# The whole browser suite shares one process, so the production limits (6 calls
# a minute, 1 in flight) would make later tests fail with 429 for reasons that
# have nothing to do with what they check, and would stop a deliberately slow
# request from overlapping a second one. The limiter is relaxed here and its
# real behaviour is covered by tests/integration/test_ai_api.py instead.
ai_extraction.MAX_CONCURRENT = 50
ai_extraction.limiter = ai_extraction.RateLimiter(max_per_minute=500)

DRAFT = {
    "title": "Payments migration, week 38",
    "summary": "The login refactor is finished and 12 of 18 merchant accounts have moved.",
    "completed_items": ["Finished the login refactor", "Moved 12 of 18 merchant accounts"],
    "next_steps": ["Start the reconciliation dry run"],
    "risks": ["The vendor has not given a date for credential rotation"],
    "review_notes": [
        "No date was given for the credential rotation",
        "The remaining six accounts are not described",
    ],
}

# Markers a test types into the source text to choose the outcome.
TIMEOUT = "TRIGGER_TIMEOUT"
MALFORMED = "TRIGGER_MALFORMED"
FILTERED = "TRIGGER_FILTERED"
SLOW = "TRIGGER_SLOW"


class ScriptedProvider:
    def complete(self, prompt: str, source_text: str) -> str:
        if TIMEOUT in source_text:
            raise TimeoutError("scripted timeout")
        if FILTERED in source_text:
            raise AIError(
                422, "The content filter rejected this text. Edit the note and try again."
            )
        if MALFORMED in source_text:
            return "not json at all"
        if SLOW in source_text:
            time.sleep(1.5)
        # Echo a slice of the source so a test can tell one answer from another.
        draft = dict(DRAFT)
        draft["title"] = f"Draft for: {source_text.strip().splitlines()[0][:60]}"
        return json.dumps(draft)


app.dependency_overrides[get_ai_provider] = lambda: ScriptedProvider()
