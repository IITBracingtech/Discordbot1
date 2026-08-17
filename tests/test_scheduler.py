import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.database.base import Base
from backend.models.core import Server, Project, Channel, Task, Reminder
from backend.scheduler.scheduler import ReminderScheduler, send_task_reminder


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
async def test_schedule_task_reminders_future_4_days(async_session: AsyncSession):
    # Mock bot client
    bot = MagicMock()
    
    # Seed tables
    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Controls", server_id=server.id)
    async_session.add(project)
    
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)
    await async_session.commit()

    # Task due date is set 4 days in the future
    due_date = datetime.now(timezone.utc) + timedelta(days=4)
    task = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-1",
        title="Code Steering Sensor Reading",
        status="Not Started",
        priority="High",
        due_date=due_date
    )
    async_session.add(task)
    await async_session.commit()

    # Instantiate scheduler
    rem_scheduler = ReminderScheduler(bot)
    
    # Run scheduling
    await rem_scheduler.schedule_task_reminders(task, async_session)
    await async_session.commit()

    # Verify that all 6 reminder records were scheduled in DB (3d, 1d, 6h, 1h, 15m, deadline)
    from sqlalchemy import select
    result = await async_session.execute(select(Reminder).where(Reminder.task_id == task.id))
    reminders = result.scalars().all()
    assert len(reminders) == 6
    
    # Assert they are sorted or have correct statuses
    for r in reminders:
        assert r.status == "SCHEDULED"


@pytest.mark.asyncio
async def test_schedule_task_reminders_future_12_hours(async_session: AsyncSession):
    bot = MagicMock()
    
    # Seed tables
    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Controls", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)
    await async_session.commit()

    # Task due date is 12 hours in future (3d and 1d should be skipped)
    due_date = datetime.now(timezone.utc) + timedelta(hours=12)
    task = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-2",
        title="Solder Dashboard PCB",
        status="In Progress",
        priority="Urgent",
        due_date=due_date
    )
    async_session.add(task)
    await async_session.commit()

    rem_scheduler = ReminderScheduler(bot)
    await rem_scheduler.schedule_task_reminders(task, async_session)
    await async_session.commit()

    # 12 hours in future should yield 4 reminders (6h, 1h, 15m, deadline)
    from sqlalchemy import select
    result = await async_session.execute(select(Reminder).where(Reminder.task_id == task.id))
    reminders = result.scalars().all()
    assert len(reminders) == 4
    
    types = [r.reminder_type for r in reminders]
    assert "6_HOURS" in types
    assert "1_HOUR" in types
    assert "15_MIN" in types
    assert "DEADLINE" in types
    assert "3_DAYS" not in types
    assert "1_DAY" not in types


@pytest.mark.asyncio
async def test_send_task_reminder_cancelled_if_done(async_session: AsyncSession):
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
    project = Project(id=project_id, name="Controls", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)
    
    # Completed task
    task = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-completed",
        title="Verify Telemetry Script",
        status="Completed",
        priority="Medium"
    )
    async_session.add(task)
    await async_session.flush()

    reminder = Reminder(
        task_id=task.id,
        trigger_time=datetime.now(timezone.utc),
        reminder_type="1_HOUR",
        status="SCHEDULED"
    )
    async_session.add(reminder)
    await async_session.commit()

    # Invoke reminder callback
    await send_task_reminder(str(reminder.id), bot)

    # Refresh reminder
    await async_session.refresh(reminder)
    
    # Task was completed, so the reminder should be marked CANCELLED and no message sent
    assert reminder.status == "CANCELLED"


@pytest.mark.asyncio
async def test_cleanup_completed_threads_24h(async_session: AsyncSession):
    bot = MagicMock()
    class AsyncContextManagerMock:
        async def __aenter__(self):
            return async_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await async_session.commit()
    bot.db_session = MagicMock(return_value=AsyncContextManagerMock())

    # Seed channel & project
    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Controls", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)

    # Task completed 30 hours ago (should be cleaned up)
    old_task = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-old",
        title="Old Completed Task",
        status="Done",
        priority="Low",
        completed_time=datetime.now(timezone.utc) - timedelta(hours=30)
    )
    async_session.add(old_task)
    await async_session.flush()

    from backend.models.core import ThreadMapping
    thread_map = ThreadMapping(task_id=old_task.id, discord_thread_id="999888777")
    async_session.add(thread_map)
    await async_session.commit()

    # Mock discord thread object
    mock_thread = AsyncMock(spec=discord.Thread)
    bot.get_channel.return_value = mock_thread

    from backend.scheduler.scheduler import cleanup_completed_threads_24h
    await cleanup_completed_threads_24h(bot)

    # Verify mock_thread.delete() was called
    mock_thread.delete.assert_called_once()


@pytest.mark.asyncio
async def test_check_overdue_tasks_9am_escalation_and_2day_limit(async_session: AsyncSession):
    from backend.models.core import AssigneeMapping, ThreadMapping
    from backend.scheduler.scheduler import check_overdue_tasks_9am

    bot = MagicMock()
    class AsyncContextManagerMock:
        async def __aenter__(self):
            return async_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await async_session.commit()
    bot.db_session = MagicMock(return_value=AsyncContextManagerMock())

    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Controls", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)

    assignee = AssigneeMapping(
        server_id=server.id,
        discord_user_id="123456789",
        notion_user_id="notion-user-1",
        display_name="Ved"
    )
    async_session.add(assignee)
    await async_session.flush()

    now = datetime.now(timezone.utc)

    # 1. Day 1 Overdue Task (~12h past due)
    task_day1 = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-day1",
        title="Collect remaining frames",
        status="In Progress",
        priority="High",
        due_date=now - timedelta(hours=12),
        assignee_id=assignee.id
    )
    async_session.add(task_day1)
    await async_session.flush()
    async_session.add(ThreadMapping(task_id=task_day1.id, discord_thread_id="111111111"))

    # 2. Day 2 Overdue Task (~36h past due -> 1 day overdue)
    task_day2 = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-day2",
        title="Fabricate Mounting Bracket",
        status="In Progress",
        priority="High",
        due_date=now - timedelta(hours=36),
        assignee_id=assignee.id
    )
    async_session.add(task_day2)
    await async_session.flush()
    async_session.add(ThreadMapping(task_id=task_day2.id, discord_thread_id="222222222"))

    # 3. Day 3 Overdue Task (~60h past due -> 2 days overdue -> should be skipped!)
    task_day3 = Task(
        channel_id=channel.id,
        notion_page_id="notion-task-day3",
        title="Old Overdue Task",
        status="In Progress",
        priority="High",
        due_date=now - timedelta(hours=60),
        assignee_id=assignee.id
    )
    async_session.add(task_day3)
    await async_session.flush()
    async_session.add(ThreadMapping(task_id=task_day3.id, discord_thread_id="333333333"))

    await async_session.commit()

    thread_day1 = AsyncMock(spec=discord.Thread)
    thread_day2 = AsyncMock(spec=discord.Thread)

    def get_channel_side_effect(chan_id):
        if chan_id == 111111111:
            return thread_day1
        elif chan_id == 222222222:
            return thread_day2
        return None

    bot.get_channel.side_effect = get_channel_side_effect

    with patch("backend.services.notion_service.NotionService") as mock_notion:
        mock_instance = mock_notion.return_value
        mock_instance.retrieve_page = AsyncMock(return_value={"created_by": {"id": "notion-user-1"}})

        await check_overdue_tasks_9am(bot)

    # Day 1 thread should receive Day 1 overdue alert mentioning assigned person <@123456789>
    thread_day1.send.assert_called_once()
    msg_day1 = thread_day1.send.call_args.kwargs["content"]
    assert "TASK OVERDUE (Day 1)" in msg_day1
    assert "<@123456789>" in msg_day1

    # Day 2 thread should receive Task Escalation (Day 2) alert tagging assigned person <@123456789>
    thread_day2.send.assert_called_once()
    msg_day2 = thread_day2.send.call_args.kwargs["content"]
    assert "TASK ESCALATION (Day 2)" in msg_day2
    assert "<@123456789>" in msg_day2

    # Day 3 thread should receive NO message (skipped because > 2 days overdue)
    bot.get_channel.assert_any_call(111111111)
    bot.get_channel.assert_any_call(222222222)
    assert 333333333 not in [call.args[0] for call in bot.get_channel.call_args_list if call.args]


