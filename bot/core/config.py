from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env.

    All values mirror .env.example. POSTGRES_* vars are consumed by
    docker-compose only, so extra="ignore" keeps them from failing validation.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Telegram
    telegram_bot_token: str = ""

    # AI provider selection: "gemini" (default) or "claude".
    ai_provider: str = "gemini"

    # Anthropic (used when ai_provider == "claude")
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    # Google Gemini / AI Studio (used when ai_provider == "gemini")
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # PostgreSQL
    database_url: str = (
        "postgresql+asyncpg://family:family@localhost:5432/family_finance"
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # NBK exchange rates
    nbk_api_url: str = "https://nationalbank.kz/rss/get_rates.cfm"

    # NCT national catalog
    nct_api_base_url: str = "https://nationalcatalog.kz/gwp"
    nct_api_key: str | None = None
    nct_cache_ttl: int = 86400

    # App
    log_level: str = "INFO"
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
