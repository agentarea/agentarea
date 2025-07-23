from abc import ABC, abstractmethod
from uuid import UUID

from .enums import ContextType
from .models import Context


class ContextProvider(ABC):
    @abstractmethod
    async def store_context(
        self,
        content: str,
        context_type: ContextType = ContextType.FACTUAL,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> UUID:
        pass

    @abstractmethod
    async def get_context(
        self,
        query: str,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        limit: int = 10,
    ) -> list[Context]:
        pass

    @abstractmethod
    async def delete_context(self, context_id: UUID) -> bool:
        pass

    @abstractmethod
    async def update_context(self, context_id: UUID, content: str) -> Context:
        pass


class ContextRepository(ABC):
    @abstractmethod
    async def create(self, context: Context) -> Context:
        pass

    @abstractmethod
    async def get_by_id(self, context_id: UUID) -> Context | None:
        pass

    @abstractmethod
    async def update(self, context: Context) -> Context:
        pass

    @abstractmethod
    async def delete(self, context_id: UUID) -> bool:
        pass

    @abstractmethod
    async def list_by_scope(
        self,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        limit: int = 100,
    ) -> list[Context]:
        pass
