"""The Azure deployment is capped at a low tokens-per-minute rate on purpose,
to bound cost. When the cap is hit, the SDK raises RateLimitError, and the
user must be told the service is busy rather than unreachable.

The SDK client is replaced, so no request leaves the test.
"""

import httpx
import openai
import pytest

from app.services.ai_extraction import AIError
from app.services.azure_provider import AzureOpenAIProvider


class _Responses:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def create(self, **_options):
        raise self.error


class _Client:
    error: Exception

    def __init__(self, **_settings) -> None:
        self.responses = _Responses(type(self).error)


def _rate_limited() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://example.openai.azure.com/openai/responses")
    return openai.RateLimitError(
        "Rate limit reached", response=httpx.Response(429, request=request), body=None
    )


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(openai, "AzureOpenAI", _Client)
    return AzureOpenAIProvider(
        endpoint="https://example.openai.azure.com/", deployment="d", api_key="k"
    )


@pytest.mark.parametrize("call", ["notes", "image"])
def test_the_deployment_cap_reads_as_busy_not_unreachable(provider, call):
    _Client.error = _rate_limited()
    with pytest.raises(AIError) as raised:
        if call == "notes":
            provider.complete("prompt", "notes")
        else:
            provider.describe_image("prompt", "data:image/png;base64,AAAA")
    assert raised.value.status == 429
    assert "busy" in raised.value.message


def test_other_failures_are_not_mistaken_for_the_cap(provider):
    _Client.error = RuntimeError("connection reset")
    with pytest.raises(RuntimeError):
        provider.complete("prompt", "notes")
