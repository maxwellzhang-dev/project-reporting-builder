"""Azure OpenAI, behind the same interface as the fake provider.

Imported only when AI is enabled, so neither the tests nor a run without
credentials touches the SDK.

This calls the Responses API, which is the surface the portal exposes for the
gpt-5 family. The instruction prompt travels as `instructions` and the note as
`input`, so an instruction hidden inside a project note cannot rewrite the
rules (docs/architecture.md §9).

That separation is why the response format is a strict `json_schema` rather
than `json_object`: Azure rejects `json_object` unless the word "json" appears
in an `input` message, and the only way to satisfy it would be to move the
prompt into the input alongside the untrusted note. A schema has the service
enforce the shape instead, and needs no such wording.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.ai_extraction import REQUEST_TIMEOUT_SECONDS, AIError

# The shape the service is asked to return. It mirrors ProgressDraft plus
# review_notes; tests/unit/test_ai_schema.py fails if the two drift apart.
# Strict mode requires every property to appear in `required` and
# additionalProperties to be false, so an optional list is expressed as an
# empty array rather than a missing key. Length limits stay in the Pydantic
# models, which validate the answer afterwards whatever the service enforced.
DRAFT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "summary", "completed_items", "next_steps", "risks", "review_notes"],
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "completed_items": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "review_notes": {"type": "array", "items": {"type": "string"}},
    },
}


def _is_content_filter(error: Exception) -> bool:
    """Recognise a content-filter rejection without depending on wording.

    The SDK surfaces the service's code on the exception, but the shape has
    changed between versions, so both the attribute and the parsed body are
    checked and neither is assumed to exist.
    """
    if getattr(error, "code", None) == "content_filter":
        return True
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        inner = body.get("error")
        source = inner if isinstance(inner, dict) else body
        if source.get("code") == "content_filter":
            return True
        innererror = source.get("innererror")
        if isinstance(innererror, dict) and innererror.get("code") == "ContentFiltered":
            return True
    return False


class AzureOpenAIProvider:
    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_key: str,
        api_version: str | None = None,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        if not (endpoint and deployment and api_key):
            raise ValueError("Azure OpenAI endpoint, deployment and key are all required")
        self.endpoint, self.deployment, self.api_key = endpoint, deployment, api_key
        self.api_version = api_version or settings.azure_openai_api_version
        self.max_output_tokens = max_output_tokens or settings.ai_max_output_tokens
        self.reasoning_effort = (
            settings.ai_reasoning_effort if reasoning_effort is None else reasoning_effort
        )

    def complete(self, prompt: str, source_text: str) -> str:
        # Imported lazily: not needed when AI is off.
        from openai import AzureOpenAI, BadRequestError

        client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=2,
        )
        options: dict[str, Any] = {
            "model": self.deployment,
            "instructions": prompt,
            "input": source_text,
            "max_output_tokens": self.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "progress_draft",
                    "strict": True,
                    "schema": DRAFT_JSON_SCHEMA,
                }
            },
        }
        if self.reasoning_effort:
            options["reasoning"] = {"effort": self.reasoning_effort}

        try:
            response = client.responses.create(**options)
        except BadRequestError as error:
            # Azure's own content filter, including its jailbreak shield, ends
            # the request with 400 and code "content_filter". That is not an
            # outage: this particular text was refused and retrying it
            # unchanged will fail again, so it maps to 422 (invalid input)
            # rather than 502. The refused text is never echoed back.
            if _is_content_filter(error):
                raise AIError(
                    422,
                    "The content filter rejected this text. Edit the note and try again.",
                ) from error
            raise

        # An answer cut off by the token budget arrives as status "incomplete"
        # with partial or empty text. Half a draft must not become a card, so
        # anything short of "completed" is a failure.
        status = getattr(response, "status", None)
        if status != "completed":
            raise ValueError(f"response not completed: {status}")
        content = (response.output_text or "").strip()
        if not content:
            raise ValueError("empty completion")
        return content
