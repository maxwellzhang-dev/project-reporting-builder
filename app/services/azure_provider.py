"""Azure OpenAI, behind the same interface as the fake provider.

Imported only when AI is enabled, so neither the tests nor a run without
credentials touches the SDK.
"""

from __future__ import annotations

from app.services.ai_extraction import REQUEST_TIMEOUT_SECONDS

MAX_OUTPUT_TOKENS = 900
API_VERSION = "2024-10-21"


class AzureOpenAIProvider:
    def __init__(self, endpoint: str, deployment: str, api_key: str) -> None:
        if not (endpoint and deployment and api_key):
            raise ValueError("Azure OpenAI endpoint, deployment and key are all required")
        self.endpoint, self.deployment, self.api_key = endpoint, deployment, api_key

    def complete(self, prompt: str, source_text: str) -> str:
        from openai import AzureOpenAI  # imported lazily: not needed when AI is off

        client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=API_VERSION,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=2,
        )
        # The instruction prompt and the untrusted source text stay in separate
        # messages, so the note cannot rewrite the instructions (architecture §9).
        response = client.chat.completions.create(
            model=self.deployment,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": source_text},
            ],
            response_format={"type": "json_object"},
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("empty completion")
        return content
