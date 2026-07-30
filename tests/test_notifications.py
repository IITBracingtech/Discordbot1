import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.database.base import Base
from backend.models.core import Server, Project, Channel, Task
from backend.services.notification_service import NotificationService


@pytest.fixture
async def async_session() -> AsyncSession:
    """Fixture to set up SQLite database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_morning_report_generation(async_session: AsyncSession):
    bot = MagicMock()
    
    # Seed DB
    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Chassis", server_id=server.id)
    async_session.add(project)
    
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)
    
    # 1. Add Task Due Today
    task_today = Task(
        channel_id=channel.id, notion_page_id="task-today", title="CFD Simulation", status="In Progress",
        priority="Medium", due_date=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    async_session.add(task_today)

    # 2. Add Task Overdue
    task_overdue = Task(
        channel_id=channel.id, notion_page_id="task-overdue", title="Laminate Monocoque", status="In Progress",
        priority="High", due_date=datetime.now(timezone.utc) - timedelta(hours=10)
    )
    async_session.add(task_overdue)

    # 3. Add Blocked Task
    task_blocked = Task(
        channel_id=channel.id, notion_page_id="task-blocked", title="Weld Jig", status="Blocked",
        priority="Low", blocked_reason="Waiting for steel delivery"
    )
    async_session.add(task_blocked)
    await async_session.commit()

    # Generate Report
    ns = NotificationService(bot)
    embed = await ns.generate_morning_report(server.id, async_session)

    # Verify Categories Mapped
    assert embed.title == "🏁 IIT Bombay Racing - Morning Briefing (9 AM IST)"
    
    # Assert fields are present
    fields = [f.name for f in embed.fields]
    assert "📅 Due Today" in fields
    assert "🚨 Overdue Tasks" in fields
    assert "🛑 Blocked Tasks" in fields
    
    # Assert task contents appear inside fields
    today_field = next(f for f in embed.fields if f.name == "📅 Due Today")
    assert "CFD Simulation" in today_field.value

    overdue_field = next(f for f in embed.fields if f.name == "🚨 Overdue Tasks")
    assert "Laminate Monocoque" in overdue_field.value

    blocked_field = next(f for f in embed.fields if f.name == "🛑 Blocked Tasks")
    assert "Weld Jig" in blocked_field.value


@pytest.mark.asyncio
async def test_evening_report_generation(async_session: AsyncSession):
    bot = MagicMock()
    
    server = Server(id="server-1", name="IITB Racing Server")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Powertrain", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-1", project_id=project_id, notion_database_id="notion-db-1")
    async_session.add(channel)
    
    # 1. Add Completed Task
    task_completed = Task(
        channel_id=channel.id, notion_page_id="task-completed", title="Test Cell Setup", status="Completed",
        priority="Medium", completed_time=datetime.now(timezone.utc)
    )
    async_session.add(task_completed)

    # 2. Add Ongoing Task
    task_ongoing = Task(
        channel_id=channel.id, notion_page_id="task-ongoing", title="Assemble Accupack", status="In Progress",
        priority="High"
    )
    async_session.add(task_ongoing)
    await async_session.commit()

    ns = NotificationService(bot)
    embed = await ns.generate_evening_report(server.id, async_session)

    assert embed.title == "🏁 IIT Bombay Racing - Evening Debrief (7 PM IST)"
    
    fields = [f.name for f in embed.fields]
    assert "📈 Completion Rate (Total Server)" in fields
    assert "✅ Completed Today" in fields
    assert "⚙️ Still Ongoing" in fields

    # Verify completion percentage (50% because 1 completed out of 2)
    rate_field = next(f for f in embed.fields if f.name == "📈 Completion Rate (Total Server)")
    assert "50.0%" in rate_field.value
