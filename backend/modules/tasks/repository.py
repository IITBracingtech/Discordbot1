import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from backend.repositories.base import BaseRepository
from backend.models.core import Task, MessageMapping, ThreadMapping, ActivityLog, History


class TaskRepository(BaseRepository[Task]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Task, session)

    async def get_by_id(self, id: uuid.UUID) -> Task | None:
        """Fetch task with joined relationship loads (message mapping, thread mapping, assignee)."""
        query = (
            select(Task)
            .where(Task.id == id)
            .options(
                selectinload(Task.message_mapping),
                selectinload(Task.thread_mapping),
                selectinload(Task.assignee),
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_notion_page_id(self, notion_page_id: str) -> Task | None:
        """Find task mapped to a Notion page (handles formatted and unhyphenated IDs)."""
        from sqlalchemy import or_, func
        clean_id = notion_page_id.replace("-", "")
        query = (
            select(Task)
            .where(
                or_(
                    Task.notion_page_id == notion_page_id,
                    func.replace(Task.notion_page_id, "-", "") == clean_id,
                )
            )
            .options(
                selectinload(Task.message_mapping),
                selectinload(Task.thread_mapping),
                selectinload(Task.assignee),
            )
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_by_discord_message_id(self, message_id: str) -> Task | None:
        """Find task mapped to a specific Discord message."""
        query = (
            select(Task)
            .join(MessageMapping)
            .where(MessageMapping.discord_message_id == message_id)
            .options(
                selectinload(Task.message_mapping),
                selectinload(Task.thread_mapping),
                selectinload(Task.assignee),
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_discord_thread_id(self, thread_id: str) -> Task | None:
        """Find task mapped to a specific Discord thread/channel."""
        query = (
            select(Task)
            .join(ThreadMapping)
            .where(ThreadMapping.discord_thread_id == thread_id)
            .options(
                selectinload(Task.message_mapping),
                selectinload(Task.thread_mapping),
                selectinload(Task.assignee),
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_task_with_mappings(
        self, task: Task, discord_message_id: str | None = None, discord_thread_id: str | None = None
    ) -> Task:
        """Atomically persist a task along with its discord message and thread mappings."""
        self.session.add(task)
        await self.session.flush()

        if discord_message_id:
            msg_map = MessageMapping(task_id=task.id, discord_message_id=discord_message_id)
            self.session.add(msg_map)

        if discord_thread_id:
            thread_map = ThreadMapping(task_id=task.id, discord_thread_id=discord_thread_id)
            self.session.add(thread_map)

        await self.session.flush()
        return task

    async def create_message_mapping(self, task_id: uuid.UUID, discord_message_id: str) -> MessageMapping:
        """Map a task to a Discord message ID."""
        msg_map = MessageMapping(task_id=task_id, discord_message_id=discord_message_id)
        self.session.add(msg_map)
        await self.session.flush()
        return msg_map

    async def create_thread_mapping(self, task_id: uuid.UUID, discord_thread_id: str) -> ThreadMapping:
        """Map a task to a Discord thread ID."""
        thread_map = ThreadMapping(task_id=task_id, discord_thread_id=discord_thread_id)
        self.session.add(thread_map)
        await self.session.flush()
        return thread_map

    async def add_activity_log(
        self, task_id: uuid.UUID, user_id: str, action_type: str, details: str | None = None
    ) -> ActivityLog:
        """Append an audit trail log entry for task interaction."""
        log = ActivityLog(
            task_id=task_id,
            user_id=user_id,
            action_type=action_type,
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def add_history_entry(
        self,
        task_id: uuid.UUID,
        property_name: str,
        old_value: str | None,
        new_value: str | None,
        changed_by: str,
    ) -> History:
        """Append a record capturing modifications made to properties of the task."""
        hist = History(
            task_id=task_id,
            property_name=property_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            changed_at=datetime.now(timezone.utc),
        )
        self.session.add(hist)
        await self.session.flush()
        return hist

    async def get_by_channel_id(self, channel_id: str) -> list[Task]:
        """Fetch all active tasks for a specific channel."""
        query = (
            select(Task)
            .where(Task.channel_id == channel_id)
            .options(
                selectinload(Task.message_mapping),
                selectinload(Task.thread_mapping),
                selectinload(Task.assignee),
            )
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def delete_task(self, task: Task) -> None:
        """Deletes task and its associated child records from the database."""
        from sqlalchemy import delete
        from backend.models.core import Reminder

        await self.session.execute(delete(Reminder).where(Reminder.task_id == task.id))
        await self.session.execute(delete(ActivityLog).where(ActivityLog.task_id == task.id))
        await self.session.execute(delete(History).where(History.task_id == task.id))
        await self.session.execute(delete(MessageMapping).where(MessageMapping.task_id == task.id))
        await self.session.execute(delete(ThreadMapping).where(ThreadMapping.task_id == task.id))
        await self.session.delete(task)
        await self.session.flush()
