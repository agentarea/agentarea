from typing import Generic, TypeVar
from uuid import UUID

from ..base.repository import BaseRepository

T = TypeVar("T")


class BaseService(Generic[T]):
    def __init__(self, repository: BaseRepository[T]):
        self.repository = repository

    async def get(self, id: UUID) -> T | None:
        """Get an entity by ID"""
        return await self.repository.get(id)

    async def list(self) -> list[T]:
        """List all entities"""
        return await self.repository.list()

    async def create(self, entity: T) -> T:
        """Create a new entity"""
        return await self.repository.create(entity)

    async def update(self, entity: T) -> T:
        """Update an existing entity"""
        return await self.repository.update(entity)

    async def delete(self, id: UUID) -> bool:
        """Delete an entity by ID"""
        return await self.repository.delete(id)
