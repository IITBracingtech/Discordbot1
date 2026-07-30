import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database.session import get_db
from backend.api import schemas
from backend.models.core import Project, Channel, Server, SyncState

router = APIRouter()


@router.get("/projects", response_model=list[schemas.TaskResponse]) # wait, let's make it returning generic list
async def list_projects(db: AsyncSession = Depends(get_db)):
    """Lists all registered project spaces."""
    query = select(Project)
    result = await db.execute(query)
    return [{"id": p.id, "name": p.name, "server_id": p.server_id, "created_at": p.created_at} for p in result.scalars().all()]


@router.get("/channels", response_model=list[schemas.ChannelMapResponse])
async def list_channels(db: AsyncSession = Depends(get_db)):
    """Lists all active Discord channel-to-Notion mappings."""
    query = select(Channel)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/channels/map", response_model=schemas.ChannelMapResponse)
async def map_channel(payload: schemas.ChannelMapRequest, db: AsyncSession = Depends(get_db)):
    """
    Maps a Discord channel to a Notion Database ID.
    Auto-registers the server and project if not yet defined.
    """
    # 1. Ensure server exists
    server_query = select(Server).where(Server.id == payload.guild_id)
    server = (await db.execute(server_query)).scalar_one_or_none()
    if not server:
        server = Server(id=payload.guild_id, name="IITB Racing Server", created_at=datetime.now(timezone.utc))
        db.add(server)
        await db.flush()

    # 2. Get or create project
    proj_query = select(Project).where(
        (Project.server_id == payload.guild_id) & (Project.name == payload.project_name)
    )
    project = (await db.execute(proj_query)).scalar_one_or_none()
    if not project:
        project = Project(
            id=uuid.uuid4(),
            server_id=payload.guild_id,
            name=payload.project_name,
            created_at=datetime.now(timezone.utc)
        )
        db.add(project)
        await db.flush()

    # 3. Create or update Channel mapping
    chan_query = select(Channel).where(Channel.id == payload.channel_id)
    channel = (await db.execute(chan_query)).scalar_one_or_none()
    if not channel:
        channel = Channel(
            id=payload.channel_id,
            project_id=project.id,
            notion_database_id=payload.notion_database_id,
            created_at=datetime.now(timezone.utc)
        )
        db.add(channel)
    else:
        channel.project_id = project.id
        channel.notion_database_id = payload.notion_database_id

    await db.flush()

    # 4. Initialize SyncState
    sync_query = select(SyncState).where(SyncState.channel_id == payload.channel_id)
    sync_state = (await db.execute(sync_query)).scalar_one_or_none()
    if not sync_state:
        sync_state = SyncState(
            id=uuid.uuid4(),
            channel_id=payload.channel_id,
            last_sync_time=datetime.now(timezone.utc),
            status="SUCCESS"
        )
        db.add(sync_state)
    else:
        sync_state.status = "SUCCESS"
        sync_state.last_sync_time = datetime.now(timezone.utc)

    await db.commit()
    return channel
