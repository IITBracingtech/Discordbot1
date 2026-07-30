import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.database.base import Base
from backend.models.core import Server, Project, Channel, Task, History, ActivityLog
from backend.modules.tasks.buttons import TaskActionButtons
from backend.modules.tasks.modals import TaskCompletionModal


@pytest.fixture
async def async_session() -> AsyncSession:
    """Fixture to set up SQLite and return a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_button_start_callback(async_session: AsyncSession):
    # Mock bot client
    bot = MagicMock()
    class AsyncContextManagerMock:
        async def __aenter__(self):
            return async_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await async_session.commit()
    bot.db_session = MagicMock(return_value=AsyncContextManagerMock())

    # Seed
    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Chassis", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)
    
    task = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-1",
        title="Verify Aerofoils",
        status="Not Started",
        priority="Medium"
    )
    async_session.add(task)
    await async_session.commit()

    # Mock interaction
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = "user-123"
    interaction.user.__str__ = MagicMock(return_value="Jaswanth")
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    # Patch sync engine and notifications
    with patch("backend.modules.tasks.buttons.bot", bot), \
         patch("backend.sync.sync_engine.SyncEngine") as MockSyncEngine, \
         patch("backend.services.notification_service.NotificationService") as MockNotifService:
         
        mock_sync = MockSyncEngine.return_value
        mock_sync.push_task_to_notion = AsyncMock()
        mock_sync._update_discord_task_embed = AsyncMock()
        
        mock_ns = MockNotifService.return_value
        mock_ns.notify_event = AsyncMock()

        # Instantiate buttons view and call callback on the decorator function directly
        view = TaskActionButtons(task_id=str(task.id), notion_page_id=task.notion_page_id)
        await view.start_callback.callback(interaction)

        # Verify state changes in Database
        await async_session.refresh(task)
        assert task.status == "In Progress"
        assert task.updated_by == "Jaswanth"
        assert task.started_time is not None

        # Verify calls
        mock_sync.push_task_to_notion.assert_called_once()
        mock_sync._update_discord_task_embed.assert_called_once()
        interaction.followup.send.assert_called_once_with("▶️ Task is now **In Progress**.", ephemeral=True)


@pytest.mark.asyncio
async def test_completion_modal_submit(async_session: AsyncSession):
    bot = MagicMock()
    class AsyncContextManagerMock:
        async def __aenter__(self):
            return async_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await async_session.commit()
    bot.db_session = MagicMock(return_value=AsyncContextManagerMock())

    # Seed
    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Powertrain", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)
    
    task = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-2",
        title="Weld Frame Tubes",
        status="In Progress",
        priority="High"
    )
    async_session.add(task)
    await async_session.commit()

    # Mock interaction
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = "user-123"
    interaction.user.__str__ = MagicMock(return_value="Jaswanth")
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    # Instantiate Completion Modal
    modal = TaskCompletionModal(task_id=str(task.id))
    
    # Simulate user inputs by overriding with MagicMocks
    modal.summary = MagicMock()
    modal.summary.value = "Finished TIG welding chassis frame tubes."
    modal.drive = MagicMock()
    modal.drive.value = "https://drive.google.com/welding-logs"
    modal.github = MagicMock()
    modal.github.value = ""

    with patch("backend.modules.tasks.modals.bot", bot), \
         patch("backend.sync.sync_engine.SyncEngine") as MockSyncEngine, \
         patch("backend.modules.tasks.modals.NotificationService") as MockNotifService:
         
        mock_sync = MockSyncEngine.return_value
        mock_sync.push_task_to_notion = AsyncMock()
        mock_sync.resolve_task_assignee_mention = AsyncMock(return_value="<@user-123>")
        mock_sync._update_discord_task_embed = AsyncMock()
        mock_sync.notion.add_page_comment = AsyncMock()
        
        mock_ns = MockNotifService.return_value
        mock_ns.notify_event = AsyncMock()

        # Submit
        await modal.on_submit(interaction)

        # Verify DB Updates
        await async_session.refresh(task)
        assert task.status == "Done"
        assert task.completion_summary == "Finished TIG welding chassis frame tubes."
        assert task.drive_links == ["https://drive.google.com/welding-logs"]
        assert task.completed_time is not None

        # Verify operations logs
        from sqlalchemy import select
        hist_res = await async_session.execute(select(History).where(History.task_id == task.id))
        histories = hist_res.scalars().all()
        assert len(histories) == 2  # status changes and summary logs
        
        act_res = await async_session.execute(select(ActivityLog).where(ActivityLog.task_id == task.id))
        logs = act_res.scalars().all()
        assert len(logs) == 1
        assert logs[0].action_type == "Task Completed"

        mock_sync.push_task_to_notion.assert_called_once()
        mock_sync._update_discord_task_embed.assert_called_once()
