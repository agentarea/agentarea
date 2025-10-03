"""Session service dependencies for Google ADK."""

from abc import ABC, abstractmethod
from typing import Annotated, Any

from fastapi import Depends


class BaseSessionService(ABC):
    @abstractmethod
    async def get_session(self, session_id: str) -> Any:
        """Retrieve a session by ID."""
        raise NotImplementedError


async def get_session_service() -> BaseSessionService:
    """Get Google ADK session service.

    Using InMemorySessionService for development/testing.
    In production, you might want to use VertexAiSessionService or another implementation.
    """
    return BaseSessionService()


# Type alias for dependency injection
SessionServiceDep = Annotated[BaseSessionService, Depends(get_session_service)]
