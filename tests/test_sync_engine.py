import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.database.base import Base
from backend.models.core import Server, Project, Channel, Task, SyncState
from backend.modules.projects.repository import ChannelRepository
from backend.modules.tasks.repository import TaskRepository
from backend.sync.sync_engine import SyncEngine


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
async def test_pull_new_notion_task(async_session: AsyncSession):
    # Mock bot client
    bot = MagicMock()
    
    # Custom db_session mock context manager returning the async_session fixture
    @patch.object(bot, "db_session")
    def mock_db_session():
        pass
    
    # Setup mock context manager manually
    class AsyncContextManagerMock:
        async def __aenter__(self):
            return async_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await async_session.commit()
            
    bot.db_session = MagicMock(return_value=AsyncContextManagerMock())

    # Seed Server, Project, and Channel
    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Chassis", server_id=server.id)
    async_session.add(project)
    
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)
    await async_session.commit()

    # Instantiate sync engine
    engine = SyncEngine(bot)
    
    # Mock database query response from Notion (representing 1 new task page)
    mock_notion_page = {
        "id": "notion-task-page-1",
        "last_edited_time": "2026-07-25T12:00:00.000Z",
        "properties": {
            "Task": {"title": [{"text": {"content": "Machine Front upright"}}]},
            "Description": {"rich_text": [{"text": {"content": "Using CNC mill"}}]},
            "Status": {"status": {"name": "Not Started"}},
            "Priority": {"select": {"name": "High"}},
            "Due Date": {"date": None},
            "Assignee": {"people": []},
            "Drive Links": {"rich_text": []},
            "GitHub Links": {"rich_text": []}
        }
    }
    
    engine.notion.query_database = AsyncMock(return_value={"results": [mock_notion_page]})
    
    # Mock Discord message & thread creation
    engine._create_discord_task_channels = AsyncMock(return_value=("discord-msg-1", "discord-thread-1"))

    # Execute sync
    await engine.sync_channel("channel-1")

    # Verify task was added in Database
    task_repo = TaskRepository(async_session)
    task = await task_repo.get_by_notion_page_id("notion-task-page-1")
    assert task is not None
    assert task.title == "Machine Front upright"
    
    # Assert discord mapping was created
    assert task.message_mapping.discord_message_id == "discord-msg-1"
    assert task.thread_mapping.discord_thread_id == "discord-thread-1"
    engine._create_discord_task_channels.assert_called_once()


@pytest.mark.asyncio
async def test_sync_conflict_notion_wins(async_session: AsyncSession):
    # Setup mock bot client
    bot = MagicMock()
    class AsyncContextManagerMock:
        async def __aenter__(self):
            return async_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await async_session.commit()
    bot.db_session = MagicMock(return_value=AsyncContextManagerMock())

    # Seed Server, Project, Channel and Task
    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Powertrain", server_id=server.id)
    async_session.add(project)
    
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)
    
    # Existing task in database, last activity is 1 hour ago
    old_time = datetime.now(timezone.utc) - timedelta(hours=1)
    task = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-page-1",
        title="Assemble Battery Box",
        status="Not Started",
        priority="Medium",
        last_activity=old_time
    )
    async_session.add(task)
    await async_session.commit()

    engine = SyncEngine(bot)
    
    # Mock updated Notion page (edited just now)
    new_time = datetime.now(timezone.utc)
    mock_notion_page = {
        "id": "notion-task-page-1",
        "last_edited_time": new_time.isoformat(),
        "properties": {
            "Task": {"title": [{"text": {"content": "Assemble Battery Box"}}]},
            "Description": {"rich_text": []},
            "Status": {"status": {"name": "In Progress"}}, # Modified Status
            "Priority": {"select": {"name": "High"}}, # Modified Priority
            "Due Date": {"date": None},
            "Assignee": {"people": []},
            "Drive Links": {"rich_text": []},
            "GitHub Links": {"rich_text": []}
        }
    }
    
    engine.notion.query_database = AsyncMock(return_value={"results": [mock_notion_page]})
    engine._update_discord_task_embed = AsyncMock()

    # Execute sync
    await engine.sync_channel("channel-1")

    # Refresh task
    await async_session.refresh(task)
    assert task.status == "In Progress"
    assert task.priority == "High"
    engine._update_discord_task_embed.assert_called_once()
