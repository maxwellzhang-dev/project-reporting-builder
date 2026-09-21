"""Markers a browser test puts in the source text to choose the fake
provider's behaviour, and the draft it returns.

This module exists so the tests can name an outcome without importing
`ai_app`, which configures a server the moment it is imported: it turns AI on
and replaces the rate limiter. Those belong in the uvicorn process, not in the
pytest process, where they would leak into the integration tests if both
suites ever ran together.
"""

TIMEOUT = "TRIGGER_TIMEOUT"
MALFORMED = "TRIGGER_MALFORMED"
FILTERED = "TRIGGER_FILTERED"
SLOW = "TRIGGER_SLOW"
NO_METRICS = "TRIGGER_NO_METRICS"

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
    # One proposal with a stated baseline and one without. The second is the
    # case the whole feature turns on: the text gives a figure and a percentage
    # change, which is not enough to state an earlier value, so it stays null.
    "metrics": [
        {
            "title": "Onboarding completion",
            "current": 79,
            "previous": 67,
            "unit": "percent",
            "unit_label": "",
        },
        {
            "title": "New users",
            "current": 847,
            "previous": None,
            "unit": "number",
            "unit_label": "",
        },
    ],
}
