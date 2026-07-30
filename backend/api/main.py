import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import structlog

from backend.config.settings import settings
from backend.services.discord_client import bot
from backend.api.routers import tasks, projects, assignees, sync, analytics

# Load environmental configs
load_dotenv()


def configure_logging() -> None:
    """Configures structured logs using structlog."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles FastAPI startup and shutdown lifecycle hooks."""
    configure_logging()
    logger = structlog.get_logger(__name__)

    logger.info("Starting REST API application server...")

    # Start Discord Bot client in background
    if settings.DISCORD_BOT_TOKEN and settings.DISCORD_BOT_TOKEN != "mock-discord-token":
        logger.info("Starting background Discord bot client task...")
        bot_task = asyncio.create_task(bot.start(settings.DISCORD_BOT_TOKEN))
        app.state.bot_task = bot_task
    else:
        logger.warning("No live DISCORD_BOT_TOKEN configured. Discord operations disabled in background.")

    yield

    # Clean shutdown of Discord Bot
    logger.info("Stopping REST API application server...")
    if hasattr(app.state, "bot_task"):
        logger.info("Shutting down background Discord bot task...")
        if not bot.is_closed():
            await bot.close()
        app.state.bot_task.cancel()
        try:
            await app.state.bot_task
        except asyncio.CancelledError:
            pass
        logger.info("Discord bot task shutdown complete.")


app = FastAPI(
    title="IIT Bombay Racing - Operations Dashboard REST API",
    description="Synchronized task operations platform connecting Discord and Notion.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Policy configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Route endpoints registrations
app.include_router(tasks.router, prefix="/api", tags=["Tasks"])
app.include_router(projects.router, prefix="/api", tags=["Projects & Channels"])
app.include_router(assignees.router, prefix="/api", tags=["Assignees"])
app.include_router(sync.router, prefix="/api", tags=["Sync Engine"])
app.include_router(analytics.router, prefix="/api", tags=["Analytics"])


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "bot_connected": bot.is_ready() if hasattr(bot, "user") else False,
        "bot_latency": bot.latency if (hasattr(bot, "latency") and bot.is_ready()) else None,
        "environment": settings.ENV
    }
