from fastapi import APIRouter, Depends, HTTPException
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database.session import get_db
from backend.models.core import SyncState, Channel
from backend.services.discord_client import bot
from backend.sync.sync_engine import SyncEngine

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/sync")


@router.get("/status/{channel_id}")
async def get_sync_status(channel_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieves the sync state record details (status, last execution, error) for a channel."""
    query = select(SyncState).where(SyncState.channel_id == channel_id)
    state = (await db.execute(query)).scalar_one_or_none()
    if not state:
        raise HTTPException(
            status_code=404,
            detail=f"Sync status mapping not found for channel {channel_id}."
        )
    return {
        "channel_id": state.channel_id,
        "status": state.status,
        "last_sync_time": state.last_sync_time,
        "notion_cursor": state.notion_cursor,
        "discord_cursor": state.discord_cursor,
        "last_error": state.last_error
    }


@router.post("/trigger/{channel_id}")
async def trigger_channel_sync(channel_id: str, db: AsyncSession = Depends(get_db)):
    """
    Manually triggers an immediate out-of-band Notion-to-Discord sync sweep
    for the specified channel mapping.
    """
    # Verify channel exists
    query = select(Channel).where(Channel.id == channel_id)
    channel = (await db.execute(query)).scalar_one_or_none()
    if not channel:
        raise HTTPException(
            status_code=404,
            detail=f"Channel {channel_id} is not configured/mapped in the system."
        )

    # Run the sync engine sweep for this channel
    sync_engine = SyncEngine(bot)
    try:
        await sync_engine.sync_channel(channel_id)
        return {
            "status": "success",
            "message": f"Successfully executed synchronization sweep for channel {channel_id}."
        }
    except Exception as e:
        logger.error("Failed manual channel sync trigger", channel_id=channel_id, error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Failed to execute channel sync sweep: {str(e)}"
        )
