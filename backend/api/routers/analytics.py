from fastapi import APIRouter, Depends, HTTPException
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database.session import get_db
from backend.services.analytics_service import AnalyticsService
from backend.services.discord_client import bot

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/analytics")


@router.get("/{server_id}")
async def get_server_analytics(server_id: str, db: AsyncSession = Depends(get_db)):
    """Computes and retrieves live productivity performance metrics for a server/guild."""
    analytics_svc = AnalyticsService(bot)
    try:
        metrics = await analytics_svc.calculate_server_metrics(server_id, db)
        await db.commit()
        return metrics
    except Exception as e:
        logger.error("Failed to fetch server metrics from REST API", server_id=server_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Internal database calculations failed: {str(e)}"
        )
