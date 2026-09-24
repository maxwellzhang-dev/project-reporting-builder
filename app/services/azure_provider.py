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
METRIC_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "current", "previous", "unit", "unit_label"],
    "properties": {
        "title": {"type": "string"},
        "current": {"type": "number"},
        # Nullable rather than omitted: strict mode requires every property in
        # `required`, and a null previous is the correct answer whenever the
        # text states a current figure but no earlier one.
        "previous": {"type": ["number", "null"]},
        "unit": {"type": "string", "enum": ["number", "percent", "custom"]},
        "unit_label": {"type": "string"},
    },
}

DRAFT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "summary",
        "completed_items",
        "next_steps",
        "risks",
        "metrics",
        "review_notes",
    ],
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "completed_items": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "metrics": {"type": "array", "items": METRIC_ITEM_SCHEMA},
        "review_notes": {"type": "array", "items": {"type": "string"}},
    },
}

# The image description: mirrors ImageDraft plus review_notes.
IMAGE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["alt_text", "caption", "review_notes"],
    "properties": {
        "alt_text": {"type": "string"},
        "caption": {"type": "string"},
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

    def complete(self, prompt: str, source_text: str, image_data_url: str | None = None) -> str:
        # Text alone stays a plain string input, as before. With an image
        # the user message carries the notes (if any) and the image as parts;
        # the prompt stays in `instructions` either way.
        user_input: str | list[dict[str, Any]] = source_text
        if image_data_url is not None:
            parts: list[dict[str, Any]] = []
            if source_text:
                parts.append({"type": "input_text", "text": source_text})
            parts.append({"type": "input_image", "image_url": image_data_url})
            user_input = [{"role": "user", "content": parts}]
        return self._respond(
            prompt,
            user_input,
            "progress_draft",
            DRAFT_JSON_SCHEMA,
            "The content filter rejected this text. Edit the note and try again.",
        )

    def describe_image(self, prompt: str, image_data_url: str) -> str:
        # The image is the whole user message: there is no user text beside
        # it, so nothing but the image can compete with the instructions.
        message = [
            {"role": "user", "content": [{"type": "input_image", "image_url": image_data_url}]}
        ]
        return self._respond(
            prompt,
            message,
            "image_draft",
            IMAGE_JSON_SCHEMA,
            "The content filter rejected this image. Try a different image.",
        )

    def _respond(
        self,
        prompt: str,
        user_input: str | list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        filtered_message: str,
    ) -> str:
        # Imported lazily: not needed when AI is off.
        from openai import AzureOpenAI, BadRequestError, RateLimitError

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
            "input": user_input,
            "max_output_tokens": self.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        if self.reasoning_effort:
            options["reasoning"] = {"effort": self.reasoning_effort}

        try:
            response = client.responses.create(**options)
        except RateLimitError as error:
            # The deployment's own tokens-per-minute cap, set low on purpose to
            # bound cost. That is "busy", not "unreachable", and says so.
            raise AIError(429, "The AI service is busy. Try again in a minute.") from error
        except BadRequestError as error:
            # Azure's own content filter, including its jailbreak shield, ends
            # the request with 400 and code "content_filter". That is not an
            # outage: this particular text was refused and retrying it
            # unchanged will fail again, so it maps to 422 (invalid input)
            # rather than 502. The refused text is never echoed back.
            if _is_content_filter(error):
                raise AIError(422, filtered_message) from error
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
