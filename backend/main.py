import asyncio
import logging
import sys
from dotenv import load_dotenv
import structlog
from backend.config.settings import settings
from backend.services.discord_client import bot

# Load environment configurations
load_dotenv()


def configure_logging() -> None:
    """Configures structured logs utilizing structlog."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    
    # Configure stdlib logging backend
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer() if settings.ENV == "production" else structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


async def main() -> None:
    configure_logging()
    logger = structlog.get_logger(__name__)

    logger.info(
        "Starting Discord Notion Sync Platform...",
        env=settings.ENV,
        timezone=settings.TIMEZONE
    )

    if settings.DISCORD_BOT_TOKEN == "mock-discord-token" or not settings.DISCORD_BOT_TOKEN:
        logger.warning(
            "DISCORD_BOT_TOKEN is set to default mock token. Bot execution skipped."
            "Configure DISCORD_BOT_TOKEN in .env for live gateway connection."
        )
        # In a mock or unit test validation, loading and compiling works.
        # We can perform a dry-run registration verify:
        await bot.setup_hook()
        logger.info("Dry-run validation success. Registered cogs loaded successfully.")
        return

    try:
        await bot.start(settings.DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot execution interrupted. Shutting down...")
    except Exception as e:
        logger.critical("Fatal bot exception crashed runner", error=str(e))
    finally:
        if not bot.is_closed():
            await bot.close()
        logger.info("Bot connection shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
