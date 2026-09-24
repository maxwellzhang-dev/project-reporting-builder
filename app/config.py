"""Application configuration, read once from the environment.

The AI settings are declared here so the container, `.env.example` and the
provider agree on their names, and default to disabled. Everything that depends
on which model is deployed is a setting rather than a constant, because the
answer changes with the deployment: a reasoning model in the gpt-5 family
spends part of its output budget on reasoning tokens, an older family does not,
and the two want different API versions.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Project Reporting Builder"

    ai_enabled: bool = False
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_key: str = ""
    # Which API surface to call. The gpt-5 family is served by the Responses
    # API, which needs a preview version; older families need a different one.
    azure_openai_api_version: str = "2025-04-01-preview"
    # Bounded so a runaway answer cannot cost more than expected. On a
    # reasoning model this budget covers reasoning tokens as well as the
    # answer, so it has to sit well above the size of the JSON draft: measured
    # against gpt-5-mini, 900 was spent entirely on reasoning and returned an
    # empty, incomplete response.
    ai_max_output_tokens: int = 2_000
    # How much reasoning to buy. Measured on gpt-5-mini with one project note:
    # "minimal" 2.3s and 0 reasoning tokens, "low" 4.4s and 192, the model's
    # own default 11.6s and 1152. All three extracted the same facts, so this
    # defaults to the cheap end. Set it to an empty string to let the model
    # decide.
    ai_reasoning_effort: str = "low"

    # How many proxies in front of the app append to X-Forwarded-For. The AI
    # rate limit is per client, and behind Azure Container Apps the socket
    # peer is the ingress, not the visitor. 0 (direct, local) ignores the
    # header completely, because a client can send any value it likes; 1 takes
    # the last entry, the one the ingress added. Set to 1 in deployment.
    trusted_proxy_hops: int = 0


settings = Settings()
