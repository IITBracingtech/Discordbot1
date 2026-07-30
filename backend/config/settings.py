import os
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # App Config
    ENV: Literal["development", "production", "testing"] = "development"
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Database (Supabase PostgreSQL)
    # E.g. postgresql+asyncpg://user:pass@host:port/dbname
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

    # Discord Config
    DISCORD_BOT_TOKEN: str = "mock-discord-token"
    DISCORD_GUILD_ID: str = ""

    # Notion Config
    NOTION_BOT_TOKEN: str = "mock-notion-token"

    # Timezone Config
    TIMEZONE: str = "Asia/Kolkata"

    # Log Level
    LOG_LEVEL: str = "INFO"


# Global settings instance
settings = Settings()
