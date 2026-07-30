import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.database.base import Base
from backend.models.core import Server, Project, Channel, Task, AssigneeMapping, Setting
from backend.modules.projects.repository import ServerRepository, ProjectRepository, ChannelRepository
from backend.modules.tasks.repository import TaskRepository
from backend.modules.settings.repository import AssigneeMappingRepository, SettingRepository


@pytest.fixture
async def async_session() -> AsyncSession:
    """Fixture to set up an in-memory SQLite database and return a session."""
    # We use sqlite+aiosqlite for async tests
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    async with engine.begin() as conn:
        # Create all tables in memory
        await conn.run_sync(Base.metadata.create_all)
        
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session
        
    await engine.dispose()


@pytest.mark.asyncio
async def test_server_and_project_creation(async_session: AsyncSession):
    # Initialize repositories
    server_repo = ServerRepository(async_session)
    project_repo = ProjectRepository(async_session)
    
    # 1. Create Server
    server = Server(id="1234567890", name="IIT Bombay Racing")
    await server_repo.create(server)
    await async_session.commit()
    
    # Verify Server
    db_server = await server_repo.get_by_id("1234567890")
    assert db_server is not None
    assert db_server.name == "IIT Bombay Racing"
    
    # 2. Create Project
    project = Project(name="Formula Student Taskboard", server_id=server.id)
    await project_repo.create(project)
    await async_session.commit()
    
    # Verify Project
    projects = await project_repo.get_by_server_id("1234567890")
    assert len(projects) == 1
    assert projects[0].name == "Formula Student Taskboard"


@pytest.mark.asyncio
async def test_channel_and_sync_state(async_session: AsyncSession):
    server_repo = ServerRepository(async_session)
    project_repo = ProjectRepository(async_session)
    channel_repo = ChannelRepository(async_session)
    
    # Seed server and project
    server = Server(id="1234567890", name="IIT Bombay Racing")
    await server_repo.create(server)
    project = Project(name="Chassis Department", server_id=server.id)
    await project_repo.create(project)
    await async_session.commit()
    
    # Create Channel
    channel = Channel(id="9876543210", project_id=project.id, notion_database_id="notion-db-abc-123")
    await channel_repo.create(channel)
    await async_session.commit()
    
    # Verify Channel & automatic SyncState setup helper
    db_channel = await channel_repo.get_by_id("9876543210")
    assert db_channel is not None
    assert db_channel.notion_database_id == "notion-db-abc-123"
    
    # Query channel by Notion DB id
    db_channel_by_notion = await channel_repo.get_by_notion_database_id("notion-db-abc-123")
    assert db_channel_by_notion is not None
    assert db_channel_by_notion.id == "9876543210"


@pytest.mark.asyncio
async def test_task_creation_and_mappings(async_session: AsyncSession):
    server_repo = ServerRepository(async_session)
    project_repo = ProjectRepository(async_session)
    channel_repo = ChannelRepository(async_session)
    assignee_repo = AssigneeMappingRepository(async_session)
    task_repo = TaskRepository(async_session)
    
    # Seed Server, Project, Channel, Assignee
    server = Server(id="1234567890", name="IIT Bombay Racing")
    await server_repo.create(server)
    project = Project(name="Powertrain", server_id=server.id)
    await project_repo.create(project)
    channel = Channel(id="44445555", project_id=project.id, notion_database_id="powertrain-db")
    await channel_repo.create(channel)
    
    assignee = await assignee_repo.link_assignee(
        server_id=server.id,
        discord_user_id="discord-user-1",
        notion_user_id="notion-user-1",
        display_name="Jaswanth Narayana"
    )
    await async_session.commit()
    
    # Create Task
    task = Task(
        channel_id=channel.id,
        notion_page_id="notion-page-xyz-789",
        title="Design Inverter Mount",
        status="In Progress",
        priority="High",
        assignee_id=assignee.id,
        drive_links=["https://drive.google.com/test-cad"],
        github_links=["https://github.com/test-repo"],
        due_date=datetime.now(timezone.utc)
    )
    
    await task_repo.create_task_with_mappings(
        task=task,
        discord_message_id="msg-inverter-1",
        discord_thread_id="thread-inverter-1"
    )
    await async_session.commit()
    
    # Verify queries
    task_by_notion = await task_repo.get_by_notion_page_id("notion-page-xyz-789")
    assert task_by_notion is not None
    assert task_by_notion.title == "Design Inverter Mount"
    assert task_by_notion.message_mapping.discord_message_id == "msg-inverter-1"
    assert task_by_notion.thread_mapping.discord_thread_id == "thread-inverter-1"
    
    # Verify query by discord message ID
    task_by_msg = await task_repo.get_by_discord_message_id("msg-inverter-1")
    assert task_by_msg is not None
    assert task_by_msg.id == task.id
    
    # Verify query by discord thread ID
    task_by_thread = await task_repo.get_by_discord_thread_id("thread-inverter-1")
    assert task_by_thread is not None
    assert task_by_thread.id == task.id


@pytest.mark.asyncio
async def test_audit_logs_and_history(async_session: AsyncSession):
    server_repo = ServerRepository(async_session)
    project_repo = ProjectRepository(async_session)
    channel_repo = ChannelRepository(async_session)
    task_repo = TaskRepository(async_session)
    
    # Seed
    server = Server(id="1234567890", name="IIT Bombay Racing")
    await server_repo.create(server)
    project = Project(name="Aerodynamics", server_id=server.id)
    await project_repo.create(project)
    channel = Channel(id="aerodynamics-channel", project_id=project.id, notion_database_id="aero-db")
    await channel_repo.create(channel)
    
    task = Task(
        channel_id=channel.id,
        notion_page_id="notion-page-aero-1",
        title="CFD Simulation Rear Wing",
        status="Not Started",
        priority="Medium"
    )
    await task_repo.create(task)
    await async_session.commit()
    
    # Add activity log and history
    await task_repo.add_activity_log(
        task_id=task.id,
        user_id="discord-user-cfd",
        action_type="Task Started",
        details="Changed status to In Progress and triggered solver"
    )
    
    await task_repo.add_history_entry(
        task_id=task.id,
        property_name="status",
        old_value="Not Started",
        new_value="In Progress",
        changed_by="discord-user-cfd"
    )
    await async_session.commit()
    
    # Verify task audit logs
    db_task = await task_repo.get_by_id(task.id)
    assert db_task is not None
    
    from sqlalchemy import select
    from backend.models.core import ActivityLog, History
    
    log_result = await async_session.execute(select(ActivityLog).where(ActivityLog.task_id == task.id))
    logs = log_result.scalars().all()
    assert len(logs) == 1
    assert logs[0].action_type == "Task Started"
    
    hist_result = await async_session.execute(select(History).where(History.task_id == task.id))
    history = hist_result.scalars().all()
    assert len(history) == 1
    assert history[0].property_name == "status"
    assert history[0].old_value == "Not Started"
    assert history[0].new_value == "In Progress"
