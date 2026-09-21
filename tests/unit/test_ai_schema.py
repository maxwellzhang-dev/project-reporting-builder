"""The JSON schema sent to Azure must keep matching the models that validate
the answer. If a draft field is added, renamed or removed, these fail rather
than letting the service enforce a shape the application no longer accepts.

Importing the provider module does not import the OpenAI SDK or read any
credential: the SDK import inside `complete` is deliberately lazy.
"""

from app.schemas.ai import ExtractResponse, ProgressDraft
from app.services.azure_provider import DRAFT_JSON_SCHEMA


def test_schema_properties_match_the_draft_models():
    expected = set(ProgressDraft.model_fields) | {"review_notes"}
    assert set(DRAFT_JSON_SCHEMA["properties"]) == expected
    assert "review_notes" in ExtractResponse.model_fields


def test_strict_mode_requirements_hold():
    # Strict mode rejects a schema that omits a property from `required` or
    # allows extra keys, so the request would fail at the service.
    assert DRAFT_JSON_SCHEMA["additionalProperties"] is False
    assert set(DRAFT_JSON_SCHEMA["required"]) == set(DRAFT_JSON_SCHEMA["properties"])


def test_list_fields_are_arrays_of_strings():
    for name in ("completed_items", "next_steps", "risks", "review_notes"):
        assert DRAFT_JSON_SCHEMA["properties"][name] == {
            "type": "array",
            "items": {"type": "string"},
        }
