"""
Streamlined Router exposing Discord Bot Pings & API Call activity.
"""

from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Query
from backend.services.discord_client import bot
from backend.services.health_service import health_service

router = APIRouter(prefix="/health", tags=["Pings & API Activity"])


@router.get("/logs")
async def get_logs(
    limit: int = Query(100, ge=1, le=200),
    category: str | None = Query("ALL")
) -> dict[str, Any]:
    """Returns Discord bot pings and API calls history."""
    logs = health_service.get_logs(limit=limit, category=category)
    stats = health_service.get_stats(bot)
    
    return {
        "bot_connected": stats["bot_connected"],
        "current_ping_ms": stats["current_ping_ms"],
        "stats": stats,
        "logs": logs,
        "server_time": datetime.now(timezone.utc).isoformat()
    }


@router.post("/ping")
async def test_ping() -> dict[str, Any]:
    """Manually pings the Discord gateway and records the latency."""
    is_ready = bool(hasattr(bot, "is_ready") and bot.is_ready())
    latency_ms = round(bot.latency * 1000, 1) if (is_ready and hasattr(bot, "latency") and bot.latency is not None) else None

    record = health_service.record_discord_ping(
        latency_ms=latency_ms,
        title="Manual Gateway Ping",
        details="Triggered from web UI"
    )
    return {
        "status": "success",
        "record": record,
        "stats": health_service.get_stats(bot)
    }
