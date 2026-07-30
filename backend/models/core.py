import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import String, ForeignKey, Text, Float, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database.base import Base


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Discord Guild ID
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    projects: Mapped[list["Project"]] = relationship("Project", back_populates="server", cascade="all, delete-orphan")
    assignee_mappings: Mapped[list["AssigneeMapping"]] = relationship("AssigneeMapping", back_populates="server", cascade="all, delete-orphan")
    settings: Mapped[list["Setting"]] = relationship("Setting", back_populates="server", cascade="all, delete-orphan")
    analytics: Mapped[list["Analytics"]] = relationship("Analytics", back_populates="server", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    notion_workspace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    server: Mapped["Server"] = relationship("Server", back_populates="projects")
    channels: Mapped[list["Channel"]] = relationship("Channel", back_populates="project", cascade="all, delete-orphan")


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Discord Channel ID
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    notion_database_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="channels")
    sync_state: Mapped["SyncState"] = relationship("SyncState", back_populates="channel", uselist=False, cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="channel", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    notion_page_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50))  # Not Started, In Progress, Blocked, Done
    priority: Mapped[str] = mapped_column(String(50))  # Low, Medium, High, Urgent
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assignee_mappings.id", ondelete="SET NULL"), nullable=True)
    progress_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    completion_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    drive_links: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # JSON Array of strings
    github_links: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # JSON Array of strings
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)  # JSON List of Dicts (url, name, type)
    started_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Name/ID of user who edited
    last_activity: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", back_populates="tasks")
    assignee: Mapped["AssigneeMapping"] = relationship("AssigneeMapping", back_populates="tasks")
    message_mapping: Mapped["MessageMapping"] = relationship("MessageMapping", back_populates="task", uselist=False, cascade="all, delete-orphan")
    thread_mapping: Mapped["ThreadMapping"] = relationship("ThreadMapping", back_populates="task", uselist=False, cascade="all, delete-orphan")
    activity_logs: Mapped[list["ActivityLog"]] = relationship("ActivityLog", back_populates="task", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="task", cascade="all, delete-orphan")
    reminders: Mapped[list["Reminder"]] = relationship("Reminder", back_populates="task", cascade="all, delete-orphan")
    history: Mapped[list["History"]] = relationship("History", back_populates="task", cascade="all, delete-orphan")


class MessageMapping(Base):
    __tablename__ = "message_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), unique=True)
    discord_message_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="message_mapping")


class ThreadMapping(Base):
    __tablename__ = "thread_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), unique=True)
    discord_thread_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="thread_mapping")


class SyncState(Base):
    __tablename__ = "sync_states"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), unique=True)
    last_sync_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notion_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discord_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="IDLE")  # IDLE, SYNCING, FAILED
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", back_populates="sync_state")


class AssigneeMapping(Base):
    __tablename__ = "assignee_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    discord_user_id: Mapped[str] = mapped_column(String(64))
    notion_user_id: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(255))

    # Constraints
    __table_args__ = (
        UniqueConstraint("server_id", "discord_user_id", name="uq_assignee_server_discord"),
        UniqueConstraint("server_id", "notion_user_id", name="uq_assignee_server_notion"),
    )

    # Relationships
    server: Mapped["Server"] = relationship("Server", back_populates="assignee_mappings")
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="assignee")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(String(255))  # Discord or Notion User ID
    action_type: Mapped[str] = mapped_column(String(100))  # Task Created, Status Changed, Priority Changed, etc.
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="activity_logs")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    recipient_discord_id: Mapped[str] = mapped_column(String(64))
    notification_type: Mapped[str] = mapped_column(String(100))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(50), default="PENDING")  # SENT, PENDING, FAILED

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="notifications")


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    trigger_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reminder_type: Mapped[str] = mapped_column(String(50))  # 3_DAYS, 1_DAY, 6_HOURS, 1_HOUR, 15_MIN, DEADLINE, OVERDUE
    job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="SCHEDULED")  # SCHEDULED, SENT, CANCELLED

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="reminders")


class History(Base):
    __tablename__ = "history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    property_name: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="history")


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("server_id", "key", name="uq_server_setting_key"),
    )

    # Relationships
    server: Mapped["Server"] = relationship("Server", back_populates="settings")


class Analytics(Base):
    __tablename__ = "analytics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    metric_key: Mapped[str] = mapped_column(String(100))
    metric_value: Mapped[float] = mapped_column(Float)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    server: Mapped["Server"] = relationship("Server", back_populates="analytics")
