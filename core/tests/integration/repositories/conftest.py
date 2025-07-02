"""
Common fixtures for repository integration tests.

This module provides database session management, model factories,
and repository fixtures for testing AgentArea repositories.
"""

from datetime import datetime
from uuid import UUID, uuid4

import pytest_asyncio
from agentarea_agents.domain.models import Agent
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_common.base.models import BaseModel
from agentarea_llm.domain.models import LLMModel, LLMModelInstance, LLMProvider
from agentarea_llm.infrastructure.llm_model_instance_repository import (
    LLMModelInstanceRepository,
)
from agentarea_llm.infrastructure.llm_model_repository import LLMModelRepository
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import Base as MCPBase
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.infrastructure.models import Task as TaskORM
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


# SQLite foreign key support
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in str(dbapi_connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create a test database engine using in-memory SQLite."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=True,  # Enable SQL logging for debugging
    )

    # Create all tables from both metadata objects
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
        await conn.run_sync(MCPBase.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    """Create a test database session with transaction rollback."""
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Start a transaction
        await session.begin()

        yield session

        # Rollback transaction to clean up
        await session.rollback()


# Model Factories
class ModelFactory:
    """Base factory for creating test models."""

    @staticmethod
    def create_llm_provider(**kwargs) -> LLMProvider:
        """Create a test LLM provider."""
        defaults = {
            "id": str(uuid4()),
            "name": f"test-provider-{uuid4().hex[:8]}",
            "description": "Test LLM provider",
            "provider_type": "test",
            "is_builtin": True,
            "updated_at": datetime.now(),
            "created_at": datetime.now(),
        }
        defaults.update(kwargs)
        return LLMProvider(**defaults)

    @staticmethod
    def create_llm_model(provider_id: str = None, **kwargs) -> LLMModel:
        """Create a test LLM model."""
        if provider_id is None:
            provider_id = str(uuid4())

        defaults = {
            "id": str(uuid4()),
            "name": f"test-model-{uuid4().hex[:8]}",
            "description": "Test LLM model",
            "provider_id": provider_id,
            "model_type": "chat",
            "endpoint_url": "http://host.docker.internal:11434",
            "context_window": "8192",
            "status": "active",
            "is_public": True,
            "updated_at": datetime.now(),
            "created_at": datetime.now(),
        }
        defaults.update(kwargs)
        return LLMModel(**defaults)

    @staticmethod
    def create_llm_model_instance(model_id: str = None, **kwargs) -> LLMModelInstance:
        """Create a test LLM model instance."""
        if model_id is None:
            model_id = str(uuid4())

        defaults = {
            "id": str(uuid4()),
            "model_id": model_id,
            "name": f"test-instance-{uuid4().hex[:8]}",
            "description": "Test LLM model instance",
            "api_key": "test-api-key",
            "status": "active",
            "is_public": True,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        defaults.update(kwargs)
        return LLMModelInstance(**defaults)

    @staticmethod
    def create_agent(model_id: str = None, **kwargs) -> Agent:
        """Create a test agent."""
        if model_id is None:
            model_id = str(uuid4())

        defaults = {
            "id": str(uuid4()),
            "name": f"test_agent_{uuid4().hex[:8]}",
            "status": "active",
            "description": "Test agent",
            "instruction": "You are a helpful test agent",
            "model_id": model_id,
            "tools_config": None,
            "events_config": None,
            "planning": False,
        }
        defaults.update(kwargs)
        return Agent(**defaults)

    @staticmethod
    def create_mcp_server(**kwargs) -> MCPServer:
        """Create a test MCP server."""
        defaults = {
            "name": f"test-mcp-server-{uuid4().hex[:8]}",
            "description": "Test MCP server",
            "docker_image_url": "test/mcp-server:latest",
            "version": "1.0.0",
            "tags": ["test"],
            "status": "active",
            "is_public": True,
            "env_schema": [],
        }
        defaults.update(kwargs)
        return MCPServer(**defaults)

    @staticmethod
    def create_mcp_server_instance(server_spec_id: str = None, **kwargs) -> MCPServerInstance:
        """Create a test MCP server instance."""
        if server_spec_id is None:
            server_spec_id = str(uuid4())

        defaults = {
            "name": f"test-mcp-instance-{uuid4().hex[:8]}",
            "description": "Test MCP server instance",
            "server_spec_id": server_spec_id,
            "json_spec": {"env_vars": []},
            "status": "active",
        }
        defaults.update(kwargs)
        return MCPServerInstance(**defaults)

    @staticmethod
    def create_task(agent_id: UUID = None, **kwargs) -> SimpleTask:
        """Create a test simple task."""
        if agent_id is None:
            agent_id = uuid4()

        defaults = {
            "id": uuid4(),
            "title": "Test Task",
            "description": "Test task description",
            "query": "Test query for the agent",
            "status": "submitted",
            "user_id": "test-user",
            "agent_id": agent_id,
            "task_parameters": {},
            "result": None,
            "error_message": None,
        }
        defaults.update(kwargs)
        return SimpleTask(**defaults)


@pytest_asyncio.fixture
async def model_factory():
    """Provide model factory for tests."""
    return ModelFactory


# Repository Fixtures
@pytest_asyncio.fixture
async def agent_repository(db_session):
    """Provide an AgentRepository instance."""
    return AgentRepository(db_session)


@pytest_asyncio.fixture
async def llm_model_repository(db_session):
    """Provide an LLMModelRepository instance."""
    return LLMModelRepository(db_session)


@pytest_asyncio.fixture
async def llm_model_instance_repository(db_session):
    """Provide an LLMModelInstanceRepository instance."""
    return LLMModelInstanceRepository(db_session)


@pytest_asyncio.fixture
async def mcp_server_repository(db_session):
    """Provide an MCPServerRepository instance."""
    return MCPServerRepository(db_session)


@pytest_asyncio.fixture
async def mcp_server_instance_repository(db_session):
    """Provide an MCPServerInstanceRepository instance."""
    return MCPServerInstanceRepository(db_session)


@pytest_asyncio.fixture
async def task_repository(db_session):
    """Provide a TaskRepository instance."""
    return TaskRepository(db_session)
