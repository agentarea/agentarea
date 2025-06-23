"""
Simplified integration test for AgentRepository without complex fixtures.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.domain.models import Agent
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_common.base.models import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create a test database engine using in-memory SQLite."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Create all tables
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


@pytest_asyncio.fixture
async def agent_repository(db_session):
    """Provide an AgentRepository instance."""
    return AgentRepository(db_session)


def create_test_agent(**kwargs) -> Agent:
    """Create a test agent with default values."""
    defaults = {
        "id": uuid4(),
        "name": f"test_agent_{uuid4().hex[:8]}",
        "status": "active",
        "description": "Test agent",
        "instruction": "You are a helpful test agent",
        "model_id": str(uuid4()),  # model_id is String in the model
        "tools_config": None,
        "events_config": None,
        "planning": False,
    }
    defaults.update(kwargs)
    return Agent(**defaults)


class TestAgentRepository:
    """Simplified test cases for AgentRepository."""

    @pytest.mark.asyncio
    async def test_create_and_get_agent(self, agent_repository: AgentRepository):
        """Test creating and retrieving an agent."""
        # Arrange
        agent = create_test_agent(name="Test Agent")

        # Act - Create
        created_agent = await agent_repository.create(agent)

        # Assert - Create
        assert created_agent is not None
        assert created_agent.name == "Test Agent"
        assert created_agent.id == agent.id

        # Act - Get
        retrieved_agent = await agent_repository.get(created_agent.id)

        # Assert - Get
        assert retrieved_agent is not None
        assert retrieved_agent.id == created_agent.id
        assert retrieved_agent.name == "Test Agent"

    @pytest.mark.asyncio
    async def test_list_agents(self, agent_repository: AgentRepository):
        """Test listing agents."""
        # Arrange
        agent1 = create_test_agent(name="Agent 1")
        agent2 = create_test_agent(name="Agent 2")

        await agent_repository.create(agent1)
        await agent_repository.create(agent2)

        # Act
        agents = await agent_repository.list()

        # Assert
        assert len(agents) == 2
        agent_names = [agent.name for agent in agents]
        assert "Agent 1" in agent_names
        assert "Agent 2" in agent_names

    @pytest.mark.asyncio
    async def test_update_agent(self, agent_repository: AgentRepository):
        """Test updating an agent."""
        # Arrange
        agent = create_test_agent(name="Original Name")
        created_agent = await agent_repository.create(agent)

        # Modify
        created_agent.name = "Updated Name"
        created_agent.description = "Updated description"

        # Act
        updated_agent = await agent_repository.update(created_agent)

        # Assert
        assert updated_agent.name == "Updated Name"
        assert updated_agent.description == "Updated description"

        # Verify persistence
        retrieved_agent = await agent_repository.get(created_agent.id)
        assert retrieved_agent.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_agent(self, agent_repository: AgentRepository):
        """Test deleting an agent."""
        # Arrange
        agent = create_test_agent()
        created_agent = await agent_repository.create(agent)

        # Act
        delete_result = await agent_repository.delete(created_agent.id)

        # Assert
        assert delete_result is True

        # Verify deletion
        deleted_agent = await agent_repository.get(created_agent.id)
        assert deleted_agent is None

    @pytest.mark.asyncio
    async def test_get_nonexistent_agent(self, agent_repository: AgentRepository):
        """Test getting a non-existent agent returns None."""
        # Act
        result = await agent_repository.get(uuid4())

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_agent(self, agent_repository: AgentRepository):
        """Test deleting a non-existent agent returns False."""
        # Act
        result = await agent_repository.delete(uuid4())

        # Assert
        assert result is False
