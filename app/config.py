"""Application configuration, read once from the environment.

Milestone 1 does not call Azure OpenAI. The AI settings are declared here so the
container and `.env.example` agree on their names, and default to disabled.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Project Reporting Builder"

    # Planned, not implemented in milestone 1.
    ai_enabled: bool = False
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_key: str = ""


settings = Settings()
