"""Session service dependencies for Google ADK."""

from typing import Annotated
from fastapi import Depends

from google.adk.sessions import InMemorySessionService, BaseSessionService


async def get_session_service() -> BaseSessionService:
    """Get Google ADK session service.

    Using InMemorySessionService for development/testing.
    In production, you might want to use VertexAiSessionService or another implementation.
    """
    return InMemorySessionService()


# Type alias for dependency injection
SessionServiceDep = Annotated[BaseSessionService, Depends(get_session_service)]
