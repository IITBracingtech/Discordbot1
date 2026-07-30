import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from backend.database.session import get_db
from backend.api import schemas
from backend.models.core import Task, Channel, AssigneeMapping, Project
from backend.modules.tasks.repository import TaskRepository
from backend.services.notion_service import NotionService
from backend.services.discord_client import bot
from backend.sync.sync_engine import SyncEngine

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/tasks")


@router.get("", response_model=list[schemas.TaskResponse])
async def list_tasks(
    channel_id: str | None = Query(None, description="Filter by Discord Channel ID"),
    assignee_id: str | None = Query(None, description="Filter by Discord/Notion assignee user ID or mapping UUID"),
    status: str | None = Query(None, description="Filter by task status"),
    priority: str | None = Query(None, description="Filter by task priority"),
    db: AsyncSession = Depends(get_db)
):
    """Lists all tasks in the system with optional filters."""
    query = select(Task).options(
        selectinload(Task.message_mapping),
        selectinload(Task.thread_mapping),
        selectinload(Task.assignee)
    )
    
    filters = []
    if channel_id:
        filters.append(Task.channel_id == channel_id)
    if status:
        filters.append(Task.status == status)
    if priority:
        filters.append(Task.priority == priority)
    if assignee_id:
        # Try finding if it's a mapping UUID, or a Discord/Notion user ID
        try:
            assignee_uuid = uuid.UUID(assignee_id)
            filters.append(Task.assignee_id == assignee_uuid)
        except ValueError:
            # Look up the assignee mapping
            mapping_query = select(AssigneeMapping.id).where(
                (AssigneeMapping.discord_user_id == assignee_id) |
                (AssigneeMapping.notion_user_id == assignee_id)
            )
            mapping_id = (await db.execute(mapping_query)).scalar_one_or_none()
            if mapping_id:
                filters.append(Task.assignee_id == mapping_id)
            else:
                return []

    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{task_id}", response_model=schemas.TaskResponse)
async def get_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Retrieves details of a single task by its UUID."""
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@router.post("", response_model=schemas.TaskResponse)
async def create_task(payload: schemas.TaskCreate, db: AsyncSession = Depends(get_db)):
    """
    Manually creates a new task.
    Pushes it to Notion database first to get a Page ID, then maps it locally and spawns a Discord thread.
    """
    # 1. Verify channel mapping exists
    chan_query = select(Channel).where(Channel.id == payload.channel_id)
    channel = (await db.execute(chan_query)).scalar_one_or_none()
    if not channel:
        raise HTTPException(
            status_code=400,
            detail=f"Discord channel {payload.channel_id} is not mapped to any Notion database."
        )

    # 2. Resolve assignee
    assignee_mapping = None
    if payload.assignee_id:
        try:
            assignee_uuid = uuid.UUID(payload.assignee_id)
            assignee_query = select(AssigneeMapping).where(AssigneeMapping.id == assignee_uuid)
        except ValueError:
            assignee_query = select(AssigneeMapping).where(AssigneeMapping.discord_user_id == payload.assignee_id)
        assignee_mapping = (await db.execute(assignee_query)).scalar_one_or_none()

    # 3. Create page in Notion
    notion_payload = {
        "title": payload.title,
        "description": payload.description,
        "status": payload.status,
        "priority": payload.priority,
        "due_date": payload.due_date,
        "notion_assignee_id": assignee_mapping.notion_user_id if assignee_mapping else None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }

    notion_service = NotionService()
    try:
        notion_properties = notion_service.build_task_properties(notion_payload)
        notion_res = await notion_service.create_page(channel.notion_database_id, notion_properties)
        notion_page_id = notion_res["id"]
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to create page in Notion: {str(e)}"
        )

    # 4. Save Task in local DB
    task = Task(
        id=uuid.uuid4(),
        channel_id=payload.channel_id,
        notion_page_id=notion_page_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        priority=payload.priority,
        due_date=payload.due_date,
        assignee_id=assignee_mapping.id if assignee_mapping else None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    task_repo = TaskRepository(db)
    await task_repo.create_task_with_mappings(task)
    await db.flush()

    # 5. Spawn Discord Embed & Thread
    if bot.is_ready():
        try:
            sync_engine = SyncEngine(bot)
            assignee_mention = f"<@{assignee_mapping.discord_user_id}>" if assignee_mapping else None
            message_id, thread_id = await sync_engine._create_discord_task_channels(task, assignee_mention)
            if message_id and thread_id:
                await task_repo.create_message_mapping(task.id, message_id)
                await task_repo.create_thread_mapping(task.id, thread_id)
                await db.commit()
        except Exception as e:
            # Log the discord failure but do not roll back the DB since Notion & DB are already synced.
            # The sync engine loop will self-heal the missing discord threads on the next poll cycle.
            logger.error("Failed to spawn discord channels for REST task", task_id=str(task.id), error=str(e))
    else:
        logger.warning("Discord bot is offline. Thread mapping creation deferred to sync sweep.")

    # Fetch updated model to return fully populated response
    refreshed_task = await task_repo.get_by_id(task.id)
    return refreshed_task


@router.patch("/{task_id}", response_model=schemas.TaskResponse)
async def update_task(task_id: uuid.UUID, payload: schemas.TaskUpdate, db: AsyncSession = Depends(get_db)):
    """Updates an existing task's properties. Propagates changes to Notion and Discord."""
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    # Capture changes for history logs
    changed = False
    now = datetime.now(timezone.utc)

    if payload.title is not None and payload.title != task.title:
        await task_repo.add_history_entry(task.id, "title", task.title, payload.title, "API_USER")
        task.title = payload.title
        changed = True

    if payload.description is not None and payload.description != task.description:
        await task_repo.add_history_entry(task.id, "description", task.description, payload.description, "API_USER")
        task.description = payload.description
        changed = True

    if payload.status is not None and payload.status != task.status:
        await task_repo.add_history_entry(task.id, "status", task.status, payload.status, "API_USER")
        task.status = payload.status
        if payload.status in ("Done", "Completed"):
            task.completed_time = now
        elif payload.status in ("In Progress", "Ongoing"):
            task.started_time = task.started_time or now
            task.blocked_reason = None
        changed = True

    if payload.priority is not None and payload.priority != task.priority:
        await task_repo.add_history_entry(task.id, "priority", task.priority, payload.priority, "API_USER")
        task.priority = payload.priority
        changed = True

    if payload.due_date is not None and payload.due_date != task.due_date:
        await task_repo.add_history_entry(task.id, "due_date", str(task.due_date), str(payload.due_date), "API_USER")
        task.due_date = payload.due_date
        changed = True

    if payload.blocked_reason is not None and payload.blocked_reason != task.blocked_reason:
        await task_repo.add_history_entry(task.id, "blocked_reason", task.blocked_reason, payload.blocked_reason, "API_USER")
        task.blocked_reason = payload.blocked_reason
        changed = True

    if payload.assignee_id is not None:
        # Resolve assignee
        assignee_mapping = None
        if payload.assignee_id:
            try:
                assignee_uuid = uuid.UUID(payload.assignee_id)
                assignee_query = select(AssigneeMapping).where(AssigneeMapping.id == assignee_uuid)
            except ValueError:
                assignee_query = select(AssigneeMapping).where(AssigneeMapping.discord_user_id == payload.assignee_id)
            assignee_mapping = (await db.execute(assignee_query)).scalar_one_or_none()

        new_assignee_id = assignee_mapping.id if assignee_mapping else None
        if new_assignee_id != task.assignee_id:
            await task_repo.add_history_entry(
                task.id, "assignee",
                task.assignee.display_name if task.assignee else None,
                assignee_mapping.display_name if assignee_mapping else None,
                "API_USER"
            )
            task.assignee_id = new_assignee_id
            changed = True

    if changed:
        task.updated_at = now
        task.last_activity = now
        task.updated_by = "API_USER"
        await db.flush()

        # Push updates to Notion
        sync_engine = SyncEngine(bot)
        try:
            await sync_engine.push_task_to_notion(task.id, db)
        except Exception as e:
            logger.error("Failed to push REST API task updates to Notion", task_id=str(task.id), error=str(e))

        # Update Discord task embed
        if bot.is_ready():
            try:
                # Reload task relations for correct embed formatting
                refreshed = await task_repo.get_by_id(task.id)
                assignee_mention = f"<@{refreshed.assignee.discord_user_id}>" if refreshed.assignee else None
                await sync_engine._update_discord_task_embed(refreshed, assignee_mention)
            except Exception as e:
                logger.error("Failed to update discord task embed for REST task", task_id=str(task.id), error=str(e))

        await db.commit()

    return task
