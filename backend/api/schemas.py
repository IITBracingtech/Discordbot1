import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    channel_id: str = Field(..., description="Discord Channel ID where this task belongs")
    title: str = Field(..., description="Task title")
    description: str | None = Field(None, description="Optional task description")
    status: str = Field("Not Started", description="Task status (e.g. Not Started, In Progress, Blocked, Done)")
    priority: str = Field("Medium", description="Task priority (e.g. Low, Medium, High, Urgent)")
    due_date: datetime | None = Field(None, description="Task deadline in UTC")
    assignee_id: str | None = Field(None, description="Discord User ID or assignee mapping ID")


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date: datetime | None = None
    assignee_id: str | None = None
    blocked_reason: str | None = None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: str
    notion_page_id: str | None = None
    title: str
    description: str | None = None
    status: str
    priority: str
    due_date: datetime | None = None
    assignee_id: uuid.UUID | None = None
    completion_summary: str | None = None
    progress_summary: str | None = None
    drive_links: list[str] | None = None
    github_links: list[str] | None = None
    created_at: datetime
    updated_at: datetime


class ChannelMapRequest(BaseModel):
    guild_id: str
    project_name: str = "Operations"
    channel_id: str
    notion_database_id: str


class ChannelMapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: uuid.UUID
    notion_database_id: str
    created_at: datetime


class AssigneeLinkRequest(BaseModel):
    server_id: str
    discord_user_id: str
    notion_user_id: str
    display_name: str


class AssigneeLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    server_id: str
    discord_user_id: str
    notion_user_id: str
    display_name: str
