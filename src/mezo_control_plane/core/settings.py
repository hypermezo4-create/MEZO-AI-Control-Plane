from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080
    control_plane_api_key: SecretStr = Field(default=SecretStr("replace-me"))

    database_url: str = "postgresql+asyncpg://mezo:mezo@localhost:5432/mezo"
    redis_url: str = "redis://localhost:6379/0"

    gemini_api_key_primary: SecretStr = Field(default=SecretStr(""))
    gemini_api_key_secondary: SecretStr = Field(default=SecretStr(""))
    gemini_primary_model: str = "gemini-3.5-flash"
    gemini_review_model: str = "gemini-3.1-pro-preview"

    qwen_base_url: str = ""
    qwen_api_key: SecretStr = Field(default=SecretStr(""))
    qwen_model: str = "qwen-coder-primary"

    model_timeout_seconds: float = 120
    model_max_retries: int = 2
    max_agent_rounds: int = 3
    max_task_concurrency: int = 2
    api_rate_limit_requests: int = 60
    api_rate_limit_window_seconds: int = 60
    api_body_limit_bytes: int = 1_048_576
    api_timeout_seconds: float = 30
    worker_stale_seconds: int = 60

    github_app_id: str = ""
    github_app_private_key: SecretStr = Field(default=SecretStr(""))
    github_webhook_secret: SecretStr = Field(default=SecretStr(""))
    skills_repository: str = "hypermezo4-create/MEZO-Agent-Skills"
    telegram_bot_token: SecretStr = Field(default=SecretStr(""))
    telegram_allowed_user_ids: str = ""
    telegram_allowed_chat_ids: str = ""
    telegram_owner_ids: str = ""
    telegram_operator_ids: str = ""
    telegram_reviewer_ids: str = ""
    telegram_callback_secret: SecretStr = Field(default=SecretStr(""))


@lru_cache
def get_settings() -> Settings:
    return Settings()
