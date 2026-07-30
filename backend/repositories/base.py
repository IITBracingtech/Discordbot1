from typing import Generic, TypeVar, Any, Sequence
from uuid import UUID
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic repository implementation for SQLAlchemy models."""

    def __init__(self, model_class: type[T], session: AsyncSession) -> None:
        self.model_class = model_class
        self.session = session

    async def get_by_id(self, id: Any) -> T | None:
        """Fetch a record by primary key."""
        return await self.session.get(self.model_class, id)

    async def get_all(self, limit: int = 100, offset: int = 0) -> Sequence[T]:
        """Fetch all records with offset-based pagination."""
        query = select(self.model_class).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def create(self, entity: T) -> T:
        """Add a new entity to the session and flush/commit."""
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, id: Any, **kwargs: Any) -> T | None:
        """Update an existing entity dynamically and return it."""
        entity = await self.get_by_id(id)
        if not entity:
            return None
        
        for key, value in kwargs.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        
        await self.session.flush()
        return entity

    async def delete(self, id: Any) -> bool:
        """Delete an entity by id."""
        entity = await self.get_by_id(id)
        if not entity:
            return False
        await self.session.delete(entity)
        await self.session.flush()
        return True

    async def save(self, entity: T) -> T:
        """Explicitly add or merge entity and flush changes."""
        self.session.add(entity)
        await self.session.flush()
        return entity
