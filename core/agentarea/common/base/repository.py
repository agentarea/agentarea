from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional, List
from uuid import UUID

T = TypeVar('T')

class BaseRepository(ABC, Generic[T]):
    @abstractmethod
    async def get(self, id: UUID) -> Optional[T]:
        """Get an entity by ID"""
        pass
    
    @abstractmethod
    async def list(self) -> List[T]:
        """List all entities"""
        pass
    
    @abstractmethod
    async def create(self, entity: T) -> T:
        """Create a new entity"""
        pass
    
    @abstractmethod
    async def update(self, entity: T) -> T:
        """Update an existing entity"""
        pass
    
    @abstractmethod
    async def delete(self, id: UUID) -> bool:
        """Delete an entity by ID"""
        pass 