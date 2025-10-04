"""Simple base repository for CRUD operations."""

from typing import TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository[T]:
    """Base repository providing basic CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID | str) -> T | None:
        """Get a record by ID."""
        return await self.session.get(self.model_class, id)

    async def list(self) -> list[T]:
        """List all records."""
        from sqlalchemy import select

        query = select(self.model_class)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, entity: T) -> T:
        """Create a new record."""
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: T) -> T:
        """Update an existing record."""
        await self.session.merge(entity)
        await self.session.flush()
        return entity

    async def delete(self, id: UUID | str) -> bool:
        """Delete a record by ID."""
        record = await self.session.get(self.model_class, id)
        if record is None:
            return False

        await self.session.delete(record)
        await self.session.flush()
        return True
