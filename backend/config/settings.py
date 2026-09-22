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
    DISCORD_TOKEN: str = ""  # fallback / alias
    DISCORD_GUILD_ID: str = ""
    GUILD_ID: str = ""       # fallback / alias
    ENABLE_PRIVILEGED_INTENTS: bool = False

    # Notion Config
    NOTION_BOT_TOKEN: str = "mock-notion-token"

    # xAI Grok Config
    GROK_API_KEY: str = ""
    GROK_MODEL: str = "grok-2-latest"
    GROK_BASE_URL: str = "https://api.x.ai/v1"

    # Google Sheets & Attendance Config
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    SPREADSHEET_ID: str = ""
    GOOGLE_SHEET_ID: str = ""  # fallback / alias
    ATTENDANCE_ADMIN_CHANNEL_ID: int = 0
    ADMIN_VIEW_CHANNEL_ID: int = 0  # fallback / alias
    ADMIN_CHANNEL_ID: int = 0       # fallback / alias
    ATTENDANCE_DAILY_CHECK_HOUR: int = 9
    ALERT_ROLE_ID: str = ""

    # Timezone Config
    TIMEZONE: str = "Asia/Kolkata"

    # Log Level
    LOG_LEVEL: str = "INFO"

    @property
    def bot_token(self) -> str:
        return self.DISCORD_BOT_TOKEN if self.DISCORD_BOT_TOKEN != "mock-discord-token" else (self.DISCORD_TOKEN or self.DISCORD_BOT_TOKEN)


# Global settings instance
settings = Settings()
