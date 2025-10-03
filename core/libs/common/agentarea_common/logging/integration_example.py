"""Example of integrating audit logging with FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from ..auth.context import UserContext, get_user_context
from .audit_logger import get_audit_logger
from .config import setup_logging
from .context_logger import get_context_logger
from .middleware import LoggingContextMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with logging setup."""
    # Setup logging on startup
    setup_logging(level="INFO", enable_structured_logging=True, enable_audit_logging=True)

    logger = get_context_logger("agentarea.startup")
    logger.info("Application starting up")

    yield

    logger.info("Application shutting down")


def create_app_with_audit_logging() -> FastAPI:
    """Create FastAPI app with audit logging configured."""
    app = FastAPI(
        title="AgentArea API",
        description="AI Agent Orchestration Platform",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Add logging middleware
    app.add_middleware(LoggingContextMiddleware)

    return app


# Example endpoint with audit logging
def example_endpoint_with_audit_logging():
    """Example of how to use audit logging in an endpoint."""
    from fastapi import APIRouter

    router = APIRouter()

    @router.post("/agents")
    async def create_agent(agent_data: dict, user_context: UserContext = Depends(get_user_context)):
        """Create agent with audit logging."""
        # Get context logger for this request
        logger = get_context_logger("agentarea.agents", user_context)
        audit_logger = get_audit_logger()

        try:
            logger.info("Creating new agent", extra={"agent_name": agent_data.get("name")})

            # Simulate agent creation
            agent_id = "agent_123"

            # Log successful creation
            audit_logger.log_create(
                resource_type="agent",
                user_context=user_context,
                resource_id=agent_id,
                resource_data=agent_data,
                endpoint="/agents",
                method="POST",
            )

            logger.info("Agent created successfully", extra={"agent_id": agent_id})

            return {"id": agent_id, "status": "created"}

        except Exception as e:
            # Log error
            audit_logger.log_error(
                resource_type="agent",
                user_context=user_context,
                error=str(e),
                endpoint="/agents",
                method="POST",
                request_data=agent_data,
            )

            logger.error("Failed to create agent", extra={"error": str(e)})
            raise

    @router.get("/agents/{agent_id}")
    async def get_agent(agent_id: str, user_context: UserContext = Depends(get_user_context)):
        """Get agent with audit logging."""
        logger = get_context_logger("agentarea.agents", user_context)
        audit_logger = get_audit_logger()

        try:
            logger.info("Retrieving agent", extra={"agent_id": agent_id})

            # Simulate agent retrieval
            agent_data = {"id": agent_id, "name": "Test Agent"}

            # Log read access
            audit_logger.log_read(
                resource_type="agent",
                user_context=user_context,
                resource_id=agent_id,
                endpoint=f"/agents/{agent_id}",
                method="GET",
            )

            return agent_data

        except Exception as e:
            audit_logger.log_error(
                resource_type="agent",
                user_context=user_context,
                error=str(e),
                resource_id=agent_id,
                endpoint=f"/agents/{agent_id}",
                method="GET",
            )
            raise

    @router.put("/agents/{agent_id}")
    async def update_agent(
        agent_id: str, agent_data: dict, user_context: UserContext = Depends(get_user_context)
    ):
        """Update agent with audit logging."""
        logger = get_context_logger("agentarea.agents", user_context)
        audit_logger = get_audit_logger()

        try:
            logger.info("Updating agent", extra={"agent_id": agent_id})

            # Log update
            audit_logger.log_update(
                resource_type="agent",
                user_context=user_context,
                resource_id=agent_id,
                resource_data=agent_data,
                endpoint=f"/agents/{agent_id}",
                method="PUT",
            )

            return {"id": agent_id, "status": "updated"}

        except Exception as e:
            audit_logger.log_error(
                resource_type="agent",
                user_context=user_context,
                error=str(e),
                resource_id=agent_id,
                endpoint=f"/agents/{agent_id}",
                method="PUT",
                request_data=agent_data,
            )
            raise

    @router.delete("/agents/{agent_id}")
    async def delete_agent(agent_id: str, user_context: UserContext = Depends(get_user_context)):
        """Delete agent with audit logging."""
        logger = get_context_logger("agentarea.agents", user_context)
        audit_logger = get_audit_logger()

        try:
            logger.info("Deleting agent", extra={"agent_id": agent_id})

            # Log deletion
            audit_logger.log_delete(
                resource_type="agent",
                user_context=user_context,
                resource_id=agent_id,
                endpoint=f"/agents/{agent_id}",
                method="DELETE",
            )

            return {"status": "deleted"}

        except Exception as e:
            audit_logger.log_error(
                resource_type="agent",
                user_context=user_context,
                error=str(e),
                resource_id=agent_id,
                endpoint=f"/agents/{agent_id}",
                method="DELETE",
            )
            raise

    return router


# Example of repository integration
def example_repository_with_audit_logging():
    """Example of repository with built-in audit logging."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..base.models import WorkspaceScopedMixin
    from ..base.workspace_scoped_repository import WorkspaceScopedRepository

    class ExampleModel(WorkspaceScopedMixin):
        """Example model for demonstration."""

        __tablename__ = "examples"

        name: str

    class ExampleRepository(WorkspaceScopedRepository[ExampleModel]):
        """Example repository with audit logging."""

        def __init__(self, session: AsyncSession, user_context: UserContext):
            super().__init__(session, ExampleModel, user_context)

        async def create_example(self, name: str) -> ExampleModel:
            """Create example with automatic audit logging."""
            # The base repository will automatically log this creation
            return await self.create(name=name)

        async def get_example(self, example_id: str) -> ExampleModel:
            """Get example with automatic audit logging."""
            # The base repository will automatically log this read
            return await self.get_by_id(example_id)

        async def update_example(self, example_id: str, name: str) -> ExampleModel:
            """Update example with automatic audit logging."""
            # The base repository will automatically log this update
            return await self.update(example_id, name=name)

        async def delete_example(self, example_id: str) -> bool:
            """Delete example with automatic audit logging."""
            # The base repository will automatically log this deletion
            return await self.delete(example_id)

    return ExampleRepository


# Example of querying audit logs
def example_audit_log_queries():
    """Example of querying audit logs."""
    from datetime import datetime, timedelta

    from .query import AuditLogQuery

    query = AuditLogQuery()

    # Get all activity for a workspace in the last 24 hours
    yesterday = datetime.now() - timedelta(days=1)
    workspace_activity = query.get_workspace_activity(
        workspace_id="workspace123", start_time=yesterday
    )

    # Get all activity for a specific user
    user_context = UserContext(user_id="user123", workspace_id="workspace123")
    user_activity = query.get_user_activity(user_context)

    # Get history for a specific resource
    agent_history = query.get_resource_history(
        resource_type="agent", resource_id="agent123", workspace_id="workspace123"
    )

    # Get error logs for troubleshooting
    error_logs = query.get_error_logs(workspace_id="workspace123", start_time=yesterday)

    return {
        "workspace_activity": workspace_activity,
        "user_activity": user_activity,
        "agent_history": agent_history,
        "error_logs": error_logs,
    }
