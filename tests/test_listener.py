import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.database.base import Base
import discord
from backend.models.core import Server, Project, Channel, Task, ThreadMapping, History, ActivityLog
from backend.modules.tasks.listener import ThreadListenerCog, ReactionListenerCog, ThreadArchiveListenerCog


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


@pytest.fixture
def mock_bot(async_session: AsyncSession):
    """Fixture returning a mocked bot client with db_session configured."""
    bot = MagicMock()
    class AsyncContextManagerMock:
        async def __aenter__(self):
            return async_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await async_session.commit()
    bot.db_session = MagicMock(return_value=AsyncContextManagerMock())
    bot.user = MagicMock()
    bot.user.id = 9999
    return bot


@pytest.mark.asyncio
async def test_listener_start_intent(mock_bot, async_session: AsyncSession):
    """Tests that typing 'started working on this now' transitions task to In Progress."""
    # Seed
    server = Server(id="server-list-1", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Chassis", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-list-1", project_id=project_id, notion_database_id="notion-db-list-1")
    async_session.add(channel)
    task = Task(
        id=uuid.uuid4(),
        channel_id=channel.id,
        notion_page_id="notion-task-list-1",
        title="FEA simulation wing uprights",
        status="Not Started",
        priority="Medium"
    )
    async_session.add(task)
    await async_session.flush()

    thread_mapping = ThreadMapping(task_id=task.id, discord_thread_id="111111")
    async_session.add(thread_mapping)
    await async_session.commit()

    # Mock Message
    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = False
    message.author.id = "user-123"
    message.author.__str__ = MagicMock(return_value="Narayana")
    
    # Mock Channel to be a discord.Thread
    thread_channel = MagicMock(spec=discord.Thread)
    thread_channel.id = int(thread_mapping.discord_thread_id)
    message.channel = thread_channel
    message.content = "started working on this now"
    message.attachments = []
    message.add_reaction = AsyncMock()

    # Instantiate cog
    cog = ThreadListenerCog(mock_bot)

    with patch("backend.sync.sync_engine.SyncEngine") as MockSyncEngine, \
         patch("backend.modules.tasks.listener.NotificationService") as MockNotifService:
         
        mock_sync = MockSyncEngine.return_value
        mock_sync.push_task_to_notion = AsyncMock()
        mock_sync._update_discord_task_embed = AsyncMock()
        
        mock_ns = MockNotifService.return_value
        mock_ns.notify_event = AsyncMock()

        # Fire listener event
        await cog.on_thread_message(message)

        # Verify task status transitioned
        await async_session.refresh(task)
        assert task.status == "In Progress"
        assert task.started_time is not None
        
        # Verify side effects
        message.add_reaction.assert_called_once_with("▶️")
        mock_sync.push_task_to_notion.assert_called_once_with(task.id, async_session)
        mock_ns.notify_event.assert_called_once()


@pytest.mark.asyncio
async def test_listener_blocked_intent(mock_bot, async_session: AsyncSession):
    """Tests that typing 'blocked waiting for CNC vendor' marks task Blocked with reason."""
    server = Server(id="server-list-2", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Powertrain", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-list-2", project_id=project_id, notion_database_id="notion-db-list-2")
    async_session.add(channel)
    task = Task(
        id=uuid.uuid4(),
        channel_id=channel.id,
        notion_page_id="notion-task-list-2",
        title="Machine wheel shafts",
        status="In Progress",
        priority="High"
    )
    async_session.add(task)
    await async_session.flush()

    thread_mapping = ThreadMapping(task_id=task.id, discord_thread_id="222222")
    async_session.add(thread_mapping)
    await async_session.commit()

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = False
    message.author.id = "user-123"
    message.author.__str__ = MagicMock(return_value="Narayana")
    
    thread_channel = MagicMock(spec=discord.Thread)
    thread_channel.id = int(thread_mapping.discord_thread_id)
    message.channel = thread_channel
    message.content = "blocked waiting for CNC vendor"
    message.attachments = []
    message.add_reaction = AsyncMock()

    cog = ThreadListenerCog(mock_bot)

    with patch("backend.sync.sync_engine.SyncEngine") as MockSyncEngine, \
         patch("backend.modules.tasks.listener.NotificationService") as MockNotifService:
         
        mock_sync = MockSyncEngine.return_value
        mock_sync.push_task_to_notion = AsyncMock()
        mock_sync._update_discord_task_embed = AsyncMock()
        
        mock_ns = MockNotifService.return_value
        mock_ns.notify_event = AsyncMock()

        # Trigger
        await cog.on_thread_message(message)

        # Refresh
        await async_session.refresh(task)
        assert task.status == "Blocked"
        assert "CNC vendor" in task.blocked_reason

        message.add_reaction.assert_called_once_with("🛑")
        mock_sync.push_task_to_notion.assert_called_once_with(task.id, async_session)


@pytest.mark.asyncio
async def test_listener_complete_intent_prompt(mock_bot, async_session: AsyncSession):
    """Tests that typing 'done' prompts user with a confirmation button embed."""
    server = Server(id="server-list-3", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Electronics", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-list-3", project_id=project_id, notion_database_id="notion-db-list-3")
    async_session.add(channel)
    task = Task(
        id=uuid.uuid4(),
        channel_id=channel.id,
        notion_page_id="notion-task-list-3",
        title="Solder dashboard buttons",
        status="In Progress",
        priority="Medium"
    )
    async_session.add(task)
    await async_session.flush()

    thread_mapping = ThreadMapping(task_id=task.id, discord_thread_id="333333")
    async_session.add(thread_mapping)
    await async_session.commit()

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = False
    message.author.id = "user-123"
    message.author.__str__ = MagicMock(return_value="Narayana")
    
    thread_channel = MagicMock(spec=discord.Thread)
    thread_channel.id = int(thread_mapping.discord_thread_id)
    message.channel = thread_channel
    message.content = "done"
    message.attachments = []
    message.reply = AsyncMock()

    cog = ThreadListenerCog(mock_bot)
    await cog.on_thread_message(message)

    # Confirm bot replied with an embed and a button view, but task status remains In Progress
    message.reply.assert_called_once()
    await async_session.refresh(task)
    assert task.status == "In Progress"


@pytest.mark.asyncio
async def test_reaction_listener_play(mock_bot, async_session: AsyncSession):
    """Tests that reacting with ▶️ on a thread message starts the task."""
    server = Server(id="server-list-4", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Telemetry", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-list-4", project_id=project_id, notion_database_id="notion-db-list-4")
    async_session.add(channel)
    task = Task(
        id=uuid.uuid4(),
        channel_id=channel.id,
        notion_page_id="notion-task-list-4",
        title="Calibrate acceleration sensor",
        status="Not Started",
        priority="High"
    )
    async_session.add(task)
    await async_session.flush()

    thread_mapping = ThreadMapping(task_id=task.id, discord_thread_id="444444")
    async_session.add(thread_mapping)
    await async_session.commit()

    cog = ReactionListenerCog(mock_bot)

    # Setup payload
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.user_id = 1111
    payload.emoji = "▶️"
    payload.channel_id = int(thread_mapping.discord_thread_id)
    payload.member = MagicMock()
    payload.member.__str__ = MagicMock(return_value="Malla")

    # Mock Thread retrieval
    thread_channel = MagicMock(spec=discord.Thread)
    mock_bot.get_channel.return_value = thread_channel

    with patch("backend.sync.sync_engine.SyncEngine") as MockSyncEngine, \
         patch("backend.modules.tasks.listener.NotificationService") as MockNotifService:
         
        mock_sync = MockSyncEngine.return_value
        mock_sync.push_task_to_notion = AsyncMock()
        mock_sync._update_discord_task_embed = AsyncMock()
        
        mock_ns = MockNotifService.return_value
        mock_ns.notify_event = AsyncMock()

        # Fire reaction cog
        await cog.on_reaction(payload)

        # Assert task transitioned
        await async_session.refresh(task)
        assert task.status == "In Progress"


@pytest.mark.asyncio
async def test_thread_archive_uncompleted_warn(mock_bot, async_session: AsyncSession):
    """Tests that archiving an incomplete task thread unarchives it and posts a warning."""
    server = Server(id="server-list-5", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Telemetry", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-list-5", project_id=project_id, notion_database_id="notion-db-list-5")
    async_session.add(channel)
    task = Task(
        id=uuid.uuid4(),
        channel_id=channel.id,
        notion_page_id="notion-task-list-5",
        title="Calibrate gyro",
        status="In Progress",
        priority="Medium"
    )
    async_session.add(task)
    await async_session.flush()

    thread_mapping = ThreadMapping(task_id=task.id, discord_thread_id="555555")
    async_session.add(thread_mapping)
    await async_session.commit()

    cog = ThreadArchiveListenerCog(mock_bot)

    # Setup before/after threads
    before_thread = MagicMock(spec=discord.Thread)
    before_thread.archived = False

    after_thread = MagicMock(spec=discord.Thread)
    after_thread.id = int(thread_mapping.discord_thread_id)
    after_thread.archived = True
    after_thread.edit = AsyncMock()
    after_thread.send = AsyncMock()

    await cog.on_thread_update(before_thread, after_thread)

    # Check unarchival triggered
    after_thread.edit.assert_called_once_with(archived=False)
    after_thread.send.assert_called_once()
