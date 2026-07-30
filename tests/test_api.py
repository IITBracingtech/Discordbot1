import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.database.base import Base
from backend.api.main import app
from backend.database.session import get_db
from backend.models.core import Server, Project, Channel, Task, AssigneeMapping, SyncState, Analytics


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
def override_db(async_session: AsyncSession):
    """Overrides get_db dependency in FastAPI app with the test session."""
    async def _get_db():
        yield async_session
    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_check(override_db):
    """Tests GET /health endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_list_tasks(override_db, async_session: AsyncSession):
    """Tests GET /api/tasks endpoint listing and filtering."""
    # Seed
    server = Server(id="server-api-1", name="IITB Racing")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Controls", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-api-1", project_id=project_id, notion_database_id="notion-db-api-1")
    async_session.add(channel)
    task1 = Task(
        id=uuid.uuid4(),
        channel_id=channel.id,
        notion_page_id="notion-page-api-1",
        title="Check wiring harness routing",
        status="In Progress",
        priority="High"
    )
    task2 = Task(
        id=uuid.uuid4(),
        channel_id=channel.id,
        notion_page_id="notion-page-api-2",
        title="Write test firmware script",
        status="Blocked",
        priority="Medium"
    )
    async_session.add_all([task1, task2])
    await async_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. List all
        resp = await ac.get("/api/tasks")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

        # 2. Filter status
        resp_status = await ac.get("/api/tasks?status=Blocked")
        assert resp_status.status_code == 200
        assert len(resp_status.json()) == 1
        assert resp_status.json()[0]["title"] == "Write test firmware script"

        # 3. Filter priority
        resp_priority = await ac.get("/api/tasks?priority=High")
        assert resp_priority.status_code == 200
        assert len(resp_priority.json()) == 1
        assert resp_priority.json()[0]["title"] == "Check wiring harness routing"


@pytest.mark.asyncio
async def test_get_task_by_id(override_db, async_session: AsyncSession):
    """Tests GET /api/tasks/{task_id} endpoint."""
    server = Server(id="server-api-2", name="IITB Racing")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Aero", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-api-2", project_id=project_id, notion_database_id="notion-db-api-2")
    async_session.add(channel)
    task = Task(
        id=uuid.uuid4(),
        channel_id=channel.id,
        notion_page_id="notion-page-api-3",
        title="FEA simulation wing",
        status="Not Started",
        priority="Urgent"
    )
    async_session.add(task)
    await async_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Success
        resp = await ac.get(f"/api/tasks/{str(task.id)}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "FEA simulation wing"

        # Not Found
        resp_nf = await ac.get(f"/api/tasks/{str(uuid.uuid4())}")
        assert resp_nf.status_code == 404


@pytest.mark.asyncio
async def test_map_channel(override_db, async_session: AsyncSession):
    """Tests POST /api/channels/map endpoint."""
    payload = {
        "guild_id": "guild-api-1",
        "project_name": "Suspension",
        "channel_id": "channel-api-99",
        "notion_database_id": "notion-db-api-99"
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/channels/map", json=payload)
    
    assert resp.status_code == 200
    assert resp.json()["notion_database_id"] == "notion-db-api-99"

    # Confirm created in DB
    from sqlalchemy import select
    res = await async_session.execute(select(Channel).where(Channel.id == "channel-api-99"))
    channel = res.scalar_one_or_none()
    assert channel is not None
    assert channel.notion_database_id == "notion-db-api-99"


@pytest.mark.asyncio
async def test_link_assignee(override_db, async_session: AsyncSession):
    """Tests POST /api/assignees/link and GET /api/assignees."""
    link_payload = {
        "server_id": "guild-api-1",
        "discord_user_id": "discord-user-88",
        "notion_user_id": "notion-user-88",
        "display_name": "Jaswanth Narayana"
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Link mapping creation
        resp_link = await ac.post("/api/assignees/link", json=link_payload)
        assert resp_link.status_code == 200
        assert resp_link.json()["display_name"] == "Jaswanth Narayana"

        # List all mapping links
        resp_list = await ac.get("/api/assignees")
        assert resp_list.status_code == 200
        assert len(resp_list.json()) == 1
        assert resp_list.json()[0]["discord_user_id"] == "discord-user-88"


@pytest.mark.asyncio
async def test_get_sync_status(override_db, async_session: AsyncSession):
    """Tests GET /api/sync/status/{channel_id} and trigger sync."""
    server = Server(id="server-api-3", name="IITB Racing")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Chassis", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-api-3", project_id=project_id, notion_database_id="notion-db-api-3")
    async_session.add(channel)
    sync_state = SyncState(
        id=uuid.uuid4(),
        channel_id=channel.id,
        status="SUCCESS",
        last_sync_time=datetime.now(timezone.utc),
        notion_cursor="cursor-abc-123"
    )
    async_session.add(sync_state)
    await async_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Fetch status
        resp = await ac.get(f"/api/sync/status/{channel.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "SUCCESS"
        assert resp.json()["notion_cursor"] == "cursor-abc-123"

        # Trigger manual channel sync
        with patch("backend.sync.sync_engine.SyncEngine.sync_channel") as mock_sync:
            mock_sync.return_value = None
            resp_trigger = await ac.post(f"/api/sync/trigger/{channel.id}")
            assert resp_trigger.status_code == 200
            assert resp_trigger.json()["status"] == "success"
            mock_sync.assert_called_once_with(channel.id)


@pytest.mark.asyncio
async def test_get_server_analytics(override_db, async_session: AsyncSession):
    """Tests GET /api/analytics/{server_id} endpoint."""
    server = Server(id="server-api-4", name="IITB Racing")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Powertrain", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-api-4", project_id=project_id, notion_database_id="notion-db-api-4")
    async_session.add(channel)
    task = Task(
        id=uuid.uuid4(),
        channel_id=channel.id,
        notion_page_id="notion-page-api-4",
        title="Weld frame brackets",
        status="Completed",
        priority="Medium",
        started_time=datetime.now(timezone.utc) - timedelta(hours=5),
        completed_time=datetime.now(timezone.utc)
    )
    async_session.add(task)
    await async_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/api/analytics/{server.id}")
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["TOTAL_TASKS"] == 1.0
    assert data["COMPLETED_TASKS"] == 1.0
    assert data["COMPLETION_RATE"] == 100.0
    assert data["AVG_COMPLETION_TIME_HOURS"] > 0.0


@pytest.mark.asyncio
async def test_create_task_manual(override_db, async_session: AsyncSession):
    """Tests POST /api/tasks endpoint manual task creation and Discord trigger."""
    server = Server(id="server-api-5", name="IITB Racing")
    async_session.add(server)
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Electronics", server_id=server.id)
    async_session.add(project)
    channel = Channel(id="channel-api-5", project_id=project_id, notion_database_id="notion-db-api-5")
    async_session.add(channel)
    await async_session.commit()

    task_payload = {
        "channel_id": channel.id,
        "title": "Design steering wheel PCB",
        "description": "Schematic routing of buttons and screen mapping.",
        "status": "Not Started",
        "priority": "High"
    }

    # Patch Notion page creation and Discord bot routines
    with patch("backend.services.notion_service.NotionService.create_page") as mock_notion_create, \
         patch("backend.sync.sync_engine.SyncEngine._create_discord_task_channels") as mock_discord_create, \
         patch("backend.services.discord_client.bot.is_ready", return_value=True):
         
        mock_notion_create.return_value = {"id": "notion-new-page-999"}
        mock_discord_create.return_value = ("msg-id-888", "thread-id-888")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/tasks", json=task_payload)

        assert resp.status_code == 200
        assert resp.json()["title"] == "Design steering wheel PCB"
        assert resp.json()["notion_page_id"] == "notion-new-page-999"

        # Verify mappings created in DB
        from sqlalchemy import select
        res_task = await async_session.execute(select(Task).where(Task.title == "Design steering wheel PCB"))
        task_db = res_task.scalar_one_or_none()
        assert task_db is not None
        assert task_db.notion_page_id == "notion-new-page-999"
        
        # Verify sync push calls
        mock_notion_create.assert_called_once()
        mock_discord_create.assert_called_once()
