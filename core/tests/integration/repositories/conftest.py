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
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_llm.domain.models import (
    ModelInstance,
    ModelSpec,
    ProviderConfig,
    ProviderSpec,
)

# from agentarea_llm.infrastructure.llm_model_instance_repository import (
#     LLMModelInstanceRepository,
# )
# from agentarea_llm.infrastructure.llm_model_repository import LLMModelRepository
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from agentarea_mcp.domain.models import MCPServer

# from agentarea_mcp.domain.mpc_server_instance_model import Base as MCPBase
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.infrastructure.repository import TaskRepository
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

    # Create all tables from BaseModel metadata
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)

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


@pytest_asyncio.fixture(scope="function")
async def populated_db_session(test_engine):
    """Create a test database session with populated test data."""
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Start a transaction
        await session.begin()

        # Populate test data
        await _populate_test_data(session)

        yield session

        # Rollback transaction to clean up
        await session.rollback()


async def _populate_test_data(session: AsyncSession):
    """Populate test database with essential LLM data."""
    # Create Ollama provider spec
    ollama_provider_spec = ProviderSpec(
        id=UUID("183a5efc-2525-4a1e-aded-1a5d5e9ff13b"),
        provider_key="ollama",
        name="Ollama",
        description="Local and open source models through Ollama",
        provider_type="ollama_chat",
        icon="ollama",
        is_builtin=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(ollama_provider_spec)

    # Create model specs for Ollama
    qwen_model_spec = ModelSpec(
        id=uuid4(),
        provider_spec_id=UUID("183a5efc-2525-4a1e-aded-1a5d5e9ff13b"),
        model_name="qwen2.5",
        display_name="Qwen 2.5",
        description="Meta's Llama 3.1 model",
        context_window=4096,
        is_active=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(qwen_model_spec)

    llama2_model_spec = ModelSpec(
        id=uuid4(),
        provider_spec_id=UUID("183a5efc-2525-4a1e-aded-1a5d5e9ff13b"),
        model_name="llama2",
        display_name="Llama 2",
        description="Meta's Llama 2 model",
        context_window=4096,
        is_active=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(llama2_model_spec)

    mistral_model_spec = ModelSpec(
        id=uuid4(),
        provider_spec_id=UUID("183a5efc-2525-4a1e-aded-1a5d5e9ff13b"),
        model_name="mistral",
        display_name="Mistral",
        description="Mistral's open source model",
        context_window=8192,
        is_active=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(mistral_model_spec)

    # Create provider config for Ollama
    ollama_provider_config = ProviderConfig(
        id=uuid4(),
        provider_spec_id=UUID("183a5efc-2525-4a1e-aded-1a5d5e9ff13b"),
        name="Ollama Local",
        api_key="not-needed-for-ollama",
        endpoint_url="http://host.docker.internal:11434",
        is_active=True,
        is_public=True,
        workspace_id="default",
        created_by="system",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(ollama_provider_config)

    # Create model instances
    qwen_instance = ModelInstance(
        id=uuid4(),
        provider_config_id=ollama_provider_config.id,
        model_spec_id=qwen_model_spec.id,
        name="Qwen 2.5 Test Instance",
        description="Test instance for Qwen 2.5 model",
        is_active=True,
        is_public=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(qwen_instance)

    llama2_instance = ModelInstance(
        id=uuid4(),
        provider_config_id=ollama_provider_config.id,
        model_spec_id=llama2_model_spec.id,
        name="Llama 2 Test Instance",
        description="Test instance for Llama 2 model",
        is_active=True,
        is_public=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(llama2_instance)

    # Commit the test data
    await session.commit()


# Model Factories
class ModelFactory:
    """Base factory for creating test models."""

    @staticmethod
    def create_provider_spec(**kwargs) -> ProviderSpec:
        """Create a test provider spec."""
        defaults = {
            "id": uuid4(),
            "provider_key": f"test-provider-{uuid4().hex[:8]}",
            "name": f"Test Provider {uuid4().hex[:8]}",
            "description": "Test provider specification",
            "provider_type": "test",
            "icon": "test",
            "is_builtin": True,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        defaults.update(kwargs)
        return ProviderSpec(**defaults)

    @staticmethod
    def create_provider_config(provider_spec_id: UUID = None, **kwargs) -> ProviderConfig:
        """Create a test provider config."""
        if provider_spec_id is None:
            provider_spec_id = uuid4()

        defaults = {
            "id": uuid4(),
            "provider_spec_id": provider_spec_id,
            "name": f"Test Config {uuid4().hex[:8]}",
            "api_key": "test-api-key",
            "endpoint_url": "https://test.example.com",
            "is_active": True,
            "is_public": True,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        defaults.update(kwargs)
        return ProviderConfig(**defaults)

    @staticmethod
    def create_model_spec(provider_spec_id: UUID = None, **kwargs) -> ModelSpec:
        """Create a test model spec."""
        if provider_spec_id is None:
            provider_spec_id = uuid4()

        defaults = {
            "id": uuid4(),
            "provider_spec_id": provider_spec_id,
            "model_name": f"test-model-{uuid4().hex[:8]}",
            "display_name": f"Test Model {uuid4().hex[:8]}",
            "description": "Test model specification",
            "context_window": 4096,
            "is_active": True,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        defaults.update(kwargs)
        return ModelSpec(**defaults)

    @staticmethod
    def create_model_instance(
        provider_config_id: UUID = None, model_spec_id: UUID = None, **kwargs
    ) -> ModelInstance:
        """Create a test model instance."""
        if provider_config_id is None:
            provider_config_id = uuid4()
        if model_spec_id is None:
            model_spec_id = uuid4()

        defaults = {
            "id": uuid4(),
            "provider_config_id": provider_config_id,
            "model_spec_id": model_spec_id,
            "name": f"Test Instance {uuid4().hex[:8]}",
            "description": "Test model instance",
            "is_active": True,
            "is_public": True,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        defaults.update(kwargs)
        return ModelInstance(**defaults)

    # Provider and model factories
    @staticmethod
    def create_provider_spec(**kwargs) -> ProviderSpec:
        """Create a test provider spec."""
        defaults = {
            "id": uuid4(),
            "name": f"test-provider-{uuid4().hex[:8]}",
            "description": "Test LLM provider",
            "provider_type": "openai",
            "is_builtin": True,
            "updated_at": datetime.now(),
            "created_at": datetime.now(),
        }
        defaults.update(kwargs)
        return ProviderSpec(**defaults)

    @staticmethod
    def create_provider_config(provider_spec_id: UUID = None, **kwargs) -> ProviderConfig:
        """Create a test provider config."""
        if provider_spec_id is None:
            provider_spec_id = uuid4()

        defaults = {
            "id": uuid4(),
            "provider_spec_id": provider_spec_id,
            "name": f"test-config-{uuid4().hex[:8]}",
            "api_key": "test-api-key",
            "endpoint_url": "http://host.docker.internal:11434",
            "is_public": True,
            "updated_at": datetime.now(),
            "created_at": datetime.now(),
        }
        defaults.update(kwargs)
        return ProviderConfig(**defaults)

    @staticmethod
    def create_model_spec(provider_spec_id: UUID = None, **kwargs) -> ModelSpec:
        """Create a test model spec."""
        if provider_spec_id is None:
            provider_spec_id = uuid4()

        defaults = {
            "id": uuid4(),
            "provider_spec_id": provider_spec_id,
            "name": f"test-model-{uuid4().hex[:8]}",
            "description": "Test LLM model",
            "model_id": f"test-model-{uuid4().hex[:8]}",
            "context_window": 8192,
            "is_builtin": True,
            "updated_at": datetime.now(),
            "created_at": datetime.now(),
        }
        defaults.update(kwargs)
        return ModelSpec(**defaults)

    @staticmethod
    def create_model_instance(model_spec_id: UUID = None, provider_config_id: UUID = None, **kwargs) -> ModelInstance:
        """Create a test model instance."""
        if model_spec_id is None:
            model_spec_id = uuid4()
        if provider_config_id is None:
            provider_config_id = uuid4()

        defaults = {
            "id": uuid4(),
            "model_spec_id": model_spec_id,
            "provider_config_id": provider_config_id,
            "name": f"test-instance-{uuid4().hex[:8]}",
            "description": "Test LLM model instance",
            "is_public": True,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        defaults.update(kwargs)
        return ModelInstance(**defaults)

    @staticmethod
    def create_agent(model_id: UUID = None, **kwargs) -> Agent:
        """Create a test agent."""
        if model_id is None:
            model_id = uuid4()

        defaults = {
            "id": uuid4(),
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
    def create_mcp_server_instance(server_spec_id: UUID = None, **kwargs) -> MCPServerInstance:
        """Create a test MCP server instance."""
        if server_spec_id is None:
            server_spec_id = uuid4()

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


@pytest_asyncio.fixture
def user_context():
    """Create a test user context."""
    return UserContext(user_id="test-user-123", workspace_id="test-workspace-456", roles=["user"])


# Repository Fixtures
@pytest_asyncio.fixture
async def agent_repository(db_session):
    """Provide an AgentRepository instance."""
    return AgentRepository(db_session)


@pytest_asyncio.fixture
async def provider_spec_repository(db_session):
    """Provide a ProviderSpecRepository instance."""
    return ProviderSpecRepository(db_session)


@pytest_asyncio.fixture
async def provider_config_repository(db_session):
    """Provide a ProviderConfigRepository instance."""
    return ProviderConfigRepository(db_session)


@pytest_asyncio.fixture
async def model_spec_repository(db_session):
    """Provide a ModelSpecRepository instance."""
    return ModelSpecRepository(db_session)


@pytest_asyncio.fixture
async def model_instance_repository(db_session):
    """Provide a ModelInstanceRepository instance."""
    return ModelInstanceRepository(db_session)


# Legacy repository fixtures - still needed for some tests
# @pytest_asyncio.fixture
# async def llm_model_repository(db_session):
#     """Provide an LLMModelRepository instance."""
#     return LLMModelRepository(db_session)


# @pytest_asyncio.fixture
# async def llm_model_instance_repository(db_session):
#     """Provide an LLMModelInstanceRepository instance."""
#     return LLMModelInstanceRepository(db_session)


@pytest_asyncio.fixture
async def mcp_server_repository(db_session):
    """Provide an MCPServerRepository instance."""
    return MCPServerRepository(db_session)


@pytest_asyncio.fixture
async def mcp_server_instance_repository(db_session, user_context):
    """Provide an MCPServerInstanceRepository instance."""
    return MCPServerInstanceRepository(db_session, user_context)


@pytest_asyncio.fixture
async def task_repository(db_session):
    """Provide a TaskRepository instance."""
    return TaskRepository(db_session)
