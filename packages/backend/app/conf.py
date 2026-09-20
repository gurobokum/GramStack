import tomllib
from enum import Enum
from pathlib import Path
from typing import cast

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(str, Enum):
    dev = "dev"
    prod = "prod"
    test = "test"


def get_version() -> str:
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
        return cast(str, data["project"]["version"])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )

    VERSION: str = get_version()
    ENV: Env = Env.dev
    DEBUG: bool = False
    DEBUG_SQL: bool = False

    MINIAPP_URL: str

    # Required
    SECRET_KEY: SecretStr
    SECRET_KEY_VERSION: int = 1
    DATABASE_URL: SecretStr
    REDIS_URL: SecretStr
    TGBOT_NAME: str
    TGBOT_TOKEN: SecretStr

    # Required -- Storage
    STORAGE_URL: HttpUrl
    STORAGE_BUCKET: str
    STORAGE_ACCESS_KEY: SecretStr
    STORAGE_SECRET_KEY: SecretStr

    # Optional -- Public storage (a bucket served without signed urls)
    PUBLIC_STORAGE_URL: HttpUrl | None = None

    # Optional
    TGBOT_SETUP_COMMANDS: bool = False
    TGBOT_REQUIRES_INVITE: bool = False
    TGBOT_LANG_COMMAND_ENABLED: bool = False
    TGBOT_WEBHOOK_URL: str | None = None
    TGBOT_WEBHOOK_SECRET_TOKEN: SecretStr | None = None
    CORS_ALLOW_ORIGINS: list[str] = []
    LOGFIRE_TOKEN: SecretStr | None = None
    LOGFIRE_FASTAPI: bool = False
    LOGFIRE_SQLALCHEMY: bool = False
    POSTHOG_API_KEY: SecretStr | None = None
    POSTHOG_HOST: str | None = None
    # Optional -- LLM
    OPENAI_API_KEY: SecretStr


# https://github.com/pydantic/pydantic/issues/3753
settings = Settings.model_validate({})
