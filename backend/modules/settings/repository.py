from typing import Sequence
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from backend.repositories.base import BaseRepository
from backend.models.core import AssigneeMapping, Setting, Reminder, Notification, Analytics


class AssigneeMappingRepository(BaseRepository[AssigneeMapping]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AssigneeMapping, session)

    async def get_by_discord_user_id(self, server_id: str, discord_user_id: str) -> AssigneeMapping | None:
        """Find assignee mapping matching a Discord User ID inside a specific guild."""
        query = select(AssigneeMapping).where(
            and_(
                AssigneeMapping.server_id == server_id,
                AssigneeMapping.discord_user_id == discord_user_id
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_notion_user_id(
        self, server_id: str, notion_user_id: str, notion_name: str | None = None
    ) -> AssigneeMapping | None:
        """Find assignee mapping matching a Notion User ID or display name inside a specific guild."""
        from sqlalchemy import or_
        conditions = [AssigneeMapping.notion_user_id == notion_user_id]
        if notion_user_id:
            conditions.append(AssigneeMapping.display_name.ilike(f"%{notion_user_id}%"))
            conditions.append(AssigneeMapping.notion_user_id.ilike(f"%{notion_user_id}%"))
        if notion_name:
            conditions.append(AssigneeMapping.display_name.ilike(f"%{notion_name}%"))
            conditions.append(AssigneeMapping.notion_user_id.ilike(f"%{notion_name}%"))

        query = select(AssigneeMapping).where(
            and_(
                AssigneeMapping.server_id == server_id,
                or_(*conditions)
            )
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def link_assignee(
        self, server_id: str, discord_user_id: str, notion_user_id: str, display_name: str
    ) -> AssigneeMapping:
        """Create or update discord-notion mapping for a user in a guild."""
        mapping = await self.get_by_discord_user_id(server_id, discord_user_id)
        if not mapping:
            mapping = AssigneeMapping(
                server_id=server_id,
                discord_user_id=discord_user_id,
                notion_user_id=notion_user_id,
                display_name=display_name
            )
            self.session.add(mapping)
        else:
            mapping.notion_user_id = notion_user_id
            mapping.display_name = display_name
        
        await self.session.flush()
        return mapping


class SettingRepository(BaseRepository[Setting]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Setting, session)

    async def get_by_key(self, server_id: str, key: str) -> Setting | None:
        """Fetch setting value matching a specific key inside a guild."""
        query = select(Setting).where(
            and_(
                Setting.server_id == server_id,
                Setting.key == key
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def set_value(self, server_id: str, key: str, value: str) -> Setting:
        """Store key/value setting configuration for a guild."""
        setting = await self.get_by_key(server_id, key)
        if not setting:
            setting = Setting(server_id=server_id, key=key, value=value)
            self.session.add(setting)
        else:
            setting.value = value
        await self.session.flush()
        return setting


class ReminderRepository(BaseRepository[Reminder]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Reminder, session)

    async def get_pending_reminders(self) -> Sequence[Reminder]:
        """Fetch reminders that are scheduled and whose trigger times are in the past or imminent."""
        query = select(Reminder).where(
            and_(
                Reminder.status == "SCHEDULED",
                Reminder.trigger_time <= datetime.now(timezone.utc)
            )
        )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_active_scheduled_reminders(self) -> Sequence[Reminder]:
        """Fetch all reminders currently scheduled for execution."""
        query = select(Reminder).where(Reminder.status == "SCHEDULED")
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_by_task_id(self, task_id: uuid.UUID) -> Sequence[Reminder]:
        """Fetch all reminders mapped to a specific task."""
        query = select(Reminder).where(Reminder.task_id == task_id)
        result = await self.session.execute(query)
        return result.scalars().all()


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Notification, session)


class AnalyticsRepository(BaseRepository[Analytics]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Analytics, session)

    async def get_by_metric_key(self, server_id: str, metric_key: str) -> Analytics | None:
        """Fetch a specific metric value inside a guild."""
        query = select(Analytics).where(
            and_(
                Analytics.server_id == server_id,
                Analytics.metric_key == metric_key
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
