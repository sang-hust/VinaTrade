from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Vinatrade"
    database_url: str = "postgresql+asyncpg://localhost:5432/vinatrade"
    jwt_secret: str = "change-me"
    debug: bool = False

    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5"
    ai_daily_limit: int = 50

    admin_email: str = "admin@vinatrade.vn"
    admin_password: str = "admin-change-me"
    admin_name: str = "Admin"

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Vinatrade <no-reply@vinatrade.vn>"

    firebase_credentials: str = ""
    gcp_credentials_json: str = ""

    public_web_url: str = "http://localhost:8000"
    cors_origins: str = ""

    scheduler_enabled: bool = True
    universe_limit: int = 0
    media_root: str = "media"

    access_token_minutes: int = 60 * 12
    refresh_token_days: int = 30
    max_devices: int = 3

    @field_validator("database_url")
    @classmethod
    def _asyncpg(cls, v: str) -> str:
        # Railway / Neon give postgres:// or postgresql:// → force the asyncpg driver
        if v.startswith("postgres://"):
            v = "postgresql+asyncpg://" + v[len("postgres://") :]
        elif v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v.replace("?sslmode=require", "?ssl=require")

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
