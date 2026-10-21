import os
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

from fastapi import Request
import time
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.api.routers import tasks, projects, assignees, sync, analytics, health
from backend.services.health_service import health_service

@app.middleware("http")
async def track_api_calls(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    path = request.url.path
    if not path.startswith("/static") and path != "/api/health/logs":
        client_ip = request.client.host if request.client else "unknown"
        try:
            health_service.record_api_call(
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                client_ip=client_ip
            )
        except Exception:
            pass
    return response


# Route endpoints registrations
app.include_router(tasks.router, prefix="/api", tags=["Tasks"])
app.include_router(projects.router, prefix="/api", tags=["Projects & Channels"])
app.include_router(assignees.router, prefix="/api", tags=["Assignees"])
app.include_router(sync.router, prefix="/api", tags=["Sync Engine"])
app.include_router(analytics.router, prefix="/api", tags=["Analytics"])
app.include_router(health.router, prefix="/api", tags=["Health & Telemetry"])

# Static assets and Dashboard Frontend
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", tags=["Dashboard"], include_in_schema=False)
@app.get("/dashboard", tags=["Dashboard"], include_in_schema=False)
async def serve_dashboard():
    """Serves the Race Control Bot Health and Telemetry Dashboard."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Race Control API Operational. Dashboard file not found."}


@app.get("/health", tags=["Health"])
async def health_check():
    """Healthcheck endpoint used by Render and external uptime monitoring."""
    is_ready = bool(hasattr(bot, "is_ready") and bot.is_ready())
    latency_ms = None
    if is_ready and hasattr(bot, "latency") and bot.latency is not None:
        latency_ms = round(bot.latency * 1000, 2)

    # Record check in telemetry history
    try:
        health_service.record_check(
            bot_connected=is_ready,
            latency_ms=latency_ms,
            source="external_http",
            event="HTTP Healthcheck Ping",
            details="Ping received on /health",
            status="healthy" if is_ready else "disconnected"
        )
    except Exception:
        pass

    return {
        "status": "healthy" if is_ready else "disconnected",
        "bot_connected": is_ready,
        "bot_latency": bot.latency if is_ready else None,
        "environment": settings.ENV
    }
