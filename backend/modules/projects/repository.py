from typing import Sequence
import uuid
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from backend.repositories.base import BaseRepository
from backend.models.core import Server, Project, Channel, SyncState


class ServerRepository(BaseRepository[Server]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Server, session)


class ProjectRepository(BaseRepository[Project]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Project, session)

    async def get_by_server_id(self, server_id: str) -> Sequence[Project]:
        """Fetch all projects for a specific Discord guild."""
        query = select(Project).where(Project.server_id == server_id)
        result = await self.session.execute(query)
        return result.scalars().all()


class ChannelRepository(BaseRepository[Channel]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Channel, session)

    async def get_by_id(self, id: str) -> Channel | None:
        """Fetch channel with project and sync state relations loaded."""
        query = (
            select(Channel)
            .where(Channel.id == id)
            .options(
                selectinload(Channel.project),
                selectinload(Channel.sync_state)
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_notion_database_id(self, database_id: str) -> Channel | None:
        """Find channel mapping by Notion Database ID."""
        query = (
            select(Channel)
            .where(Channel.notion_database_id == database_id)
            .options(
                selectinload(Channel.project),
                selectinload(Channel.sync_state)
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_all_mapped_channels(self) -> Sequence[Channel]:
        """Fetch all channels configured with Notion Database mapping."""
        query = select(Channel).options(
            selectinload(Channel.project),
            selectinload(Channel.sync_state)
        )
        result = await self.session.execute(query)
        return result.scalars().all()


class SyncStateRepository(BaseRepository[SyncState]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(SyncState, session)

    async def get_by_channel_id(self, channel_id: str) -> SyncState | None:
        """Retrieve the sync state cursor info for a channel."""
        query = select(SyncState).where(SyncState.channel_id == channel_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_notion_cursor(self, channel_id: str, notion_cursor: str) -> SyncState | None:
        """Update Notion cursor timestamp for the sync engine."""
        sync_state = await self.get_by_channel_id(channel_id)
        if not sync_state:
            sync_state = SyncState(channel_id=channel_id, notion_cursor=notion_cursor)
            self.session.add(sync_state)
        else:
            sync_state.notion_cursor = notion_cursor
        await self.session.flush()
        return sync_state
