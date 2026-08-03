import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from notion_client import APIResponseError
from httpx import Response, Request
from backend.services.notion_service import NotionService


def test_build_task_properties():
    task_data = {
        "title": "Build Battery Cooling Chamber",
        "description": "CFD validation for cooling channels",
        "status": "In Progress",
        "priority": "Urgent",
        "due_date": datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc),
        "notion_assignee_id": "notion-user-cool",
        "drive_links": ["https://drive.google.com/battery-cfd"],
        "github_links": []
    }

    properties = NotionService.build_task_properties(task_data)

    assert properties["Task"]["title"][0]["text"]["content"] == "Build Battery Cooling Chamber"
    assert properties["Description"]["rich_text"][0]["text"]["content"] == "CFD validation for cooling channels"
    assert properties["Status"]["status"]["name"] == "In Progress"
    assert properties["Priority"]["select"]["name"] == "Urgent"
    assert properties["Due Date"]["date"]["start"] == "2026-07-27T18:00:00+00:00"
    assert properties["Assignee"]["people"][0]["id"] == "notion-user-cool"
    assert properties["Drive Links"]["rich_text"][0]["text"]["content"] == "https://drive.google.com/battery-cfd"


def test_parse_notion_properties():
    mock_page = {
        "id": "notion-page-uuid-1",
        "last_edited_time": "2026-07-25T12:00:00.000Z",
        "properties": {
            "Task": {"title": [{"text": {"content": "Fabricate Front Wing"}}]},
            "Description": {"rich_text": [{"text": {"content": "Carbon fiber layup process"}}]},
            "Status": {"status": {"name": "Blocked"}},
            "Priority": {"select": {"name": "High"}},
            "Due Date": {"date": {"start": "2026-07-30T10:00:00.000Z"}},
            "Assignee": {"people": [{"id": "notion-user-aero"}]},
            "Drive Links": {"rich_text": [{"text": {"content": "https://drive.google.com/front-wing-drawings"}}]},
            "GitHub Links": {"rich_text": []}
        }
    }

    parsed = NotionService.parse_notion_properties(mock_page)

    assert parsed["notion_page_id"] == "notion-page-uuid-1"
    assert parsed["title"] == "Fabricate Front Wing"
    assert parsed["description"] == "Carbon fiber layup process"
    assert parsed["status"] == "Blocked"
    assert parsed["priority"] == "High"
    assert parsed["due_date"] == datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
    assert parsed["notion_assignee_id"] == "notion-user-aero"
    assert parsed["drive_links"] == ["https://drive.google.com/front-wing-drawings"]


@pytest.mark.asyncio
async def test_notion_rate_limit_backoff():
    # Instantiate service
    service = NotionService(token="test-token")

    import httpx
    # Instantiate APIResponseError using the correct signature
    err = APIResponseError(
        code="rate_limited",
        status=429,
        message="Rate limited",
        headers=httpx.Headers(),
        raw_body_text="{}"
    )
    
    mock_query = AsyncMock()
    mock_query.side_effect = [
        err,
        {"results": [{"id": "page-1"}]}
    ]
    service.client.request = mock_query

    # Patch asyncio.sleep so the test runs instantly without delay
    with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
        result = await service.query_database("db-id")
        
        assert result["results"][0]["id"] == "page-1"
        assert mock_query.call_count == 2
        mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_query_database_uses_data_sources():
    service = NotionService(token="test-token")
    mock_query = AsyncMock(return_value={"results": []})
    service.client.data_sources.query = mock_query

    result = await service.query_database("my-db-id", cursor="next-cursor", page_size=50)

    assert result == {"results": []}
    mock_query.assert_called_once_with(
        data_source_id="my-db-id",
        page_size=50,
        start_cursor="next-cursor"
    )


@pytest.mark.asyncio
async def test_create_page_uses_data_source_id():
    service = NotionService(token="test-token")
    mock_create = AsyncMock(return_value={"id": "new-page-id"})
    service.client.pages.create = mock_create

    properties = {"Task name": {"title": [{"text": {"content": "Hello"}}]}}
    result = await service.create_page("my-db-id", properties)

    assert result == {"id": "new-page-id"}
    mock_create.assert_called_once_with(
        parent={"database_id": "my-db-id"},
        properties=properties
    )
