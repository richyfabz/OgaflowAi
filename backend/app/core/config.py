from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    app_name: str = "OgaFlow"
    app_env: str = "development"
    debug: bool = Field(default=False, validation_alias="OGAFLOW_DEBUG")
    database_url: SecretStr | None = None
    demo_mode: bool = Field(default=False, validation_alias="OGAFLOW_DEMO_MODE")
    agent_boundary_enabled: bool = Field(
        default=False, validation_alias="OGAFLOW_AGENT_BOUNDARY_ENABLED"
    )
    tool_token: SecretStr | None = Field(
        default=None, validation_alias="OGAFLOW_TOOL_TOKEN"
    )

    frontend_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000"

    @model_validator(mode="after")
    def validate_demo_mode(self) -> "Settings":
        if self.demo_mode and self.app_env not in {"development", "test"}:
            raise ValueError("Demo mode is limited to development and test")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
