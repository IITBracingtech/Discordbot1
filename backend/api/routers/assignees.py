from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database.session import get_db
from backend.api import schemas
from backend.models.core import AssigneeMapping, Server
from datetime import datetime, timezone

router = APIRouter(prefix="/assignees")


@router.get("", response_model=list[schemas.AssigneeLinkResponse])
async def list_assignees(db: AsyncSession = Depends(get_db)):
    """Lists all registered assignee mapping links."""
    query = select(AssigneeMapping)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/link", response_model=schemas.AssigneeLinkResponse)
async def link_assignee(payload: schemas.AssigneeLinkRequest, db: AsyncSession = Depends(get_db)):
    """Establishes or updates a link mapping a Discord User ID to a Notion User ID."""
    # Ensure server exists
    server_query = select(Server).where(Server.id == payload.server_id)
    server = (await db.execute(server_query)).scalar_one_or_none()
    if not server:
        server = Server(id=payload.server_id, name="IITB Racing Server", created_at=datetime.now(timezone.utc))
        db.add(server)
        await db.flush()

    # Create or update mapping
    query = select(AssigneeMapping).where(
        (AssigneeMapping.server_id == payload.server_id) &
        ((AssigneeMapping.discord_user_id == payload.discord_user_id) |
         (AssigneeMapping.notion_user_id == payload.notion_user_id))
    )
    mapping = (await db.execute(query)).scalar_one_or_none()
    
    if not mapping:
        import uuid
        mapping = AssigneeMapping(
            id=uuid.uuid4(),
            server_id=payload.server_id,
            discord_user_id=payload.discord_user_id,
            notion_user_id=payload.notion_user_id,
            display_name=payload.display_name
        )
        db.add(mapping)
    else:
        # Update attributes
        mapping.discord_user_id = payload.discord_user_id
        mapping.notion_user_id = payload.notion_user_id
        mapping.display_name = payload.display_name

    await db.commit()
    return mapping
