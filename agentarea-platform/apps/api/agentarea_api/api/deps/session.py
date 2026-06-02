"""Session service dependencies for Google ADK."""

from abc import ABC, abstractmethod
from typing import Annotated, Any

from fastapi import Depends


class BaseSessionService(ABC):
    @abstractmethod
    async def get_session(self, session_id: str) -> Any:
        """Retrieve a session by ID."""
        raise NotImplementedError


class InMemorySessionService(BaseSessionService):
    """Development session store used until an external ADK session backend is configured."""

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}

    async def get_session(self, session_id: str) -> Any:
        return self._sessions.get(session_id)


async def get_session_service() -> BaseSessionService:
    """Get Google ADK session service.

    Using InMemorySessionService for development/testing.
    In production, you might want to use VertexAiSessionService or another implementation.
    """
    return InMemorySessionService()


# Type alias for dependency injection
SessionServiceDep = Annotated[BaseSessionService, Depends(get_session_service)]
