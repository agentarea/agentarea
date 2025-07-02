"""
Simplified integration test for LLMModelRepository without complex fixtures.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_common.base.models import BaseModel
from agentarea_llm.domain.models import LLMModel
from agentarea_llm.infrastructure.llm_model_repository import LLMModelRepository
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
async def llm_model_repository(db_session):
    """Provide an LLMModelRepository instance."""
    return LLMModelRepository(db_session)


def create_test_llm_model(**kwargs) -> LLMModel:
    """Create a test LLM model with default values."""
    defaults = {
        "id": uuid4(),
        "name": f"test-model-{uuid4().hex[:8]}",
        "description": "Test LLM model",
        "provider_id": uuid4(),  # provider_id is UUID in the model
        "model_type": "chat",
        "endpoint_url": "http://host.docker.internal:11434",
        "context_window": "8192",
        "status": "active",
        "is_public": True,
    }
    defaults.update(kwargs)
    return LLMModel(**defaults)


class TestLLMModelRepository:
    """Simplified test cases for LLMModelRepository."""

    @pytest.mark.asyncio
    async def test_create_and_get_model(self, llm_model_repository: LLMModelRepository):
        """Test creating and retrieving an LLM model."""
        # Arrange
        model = create_test_llm_model(name="Test Model")

        # Act - Create
        created_model = await llm_model_repository.create(model)

        # Assert - Create
        assert created_model is not None
        assert created_model.name == "Test Model"
        assert created_model.id == model.id

        # Act - Get
        retrieved_model = await llm_model_repository.get(created_model.id)

        # Assert - Get
        assert retrieved_model is not None
        assert retrieved_model.id == created_model.id
        assert retrieved_model.name == "Test Model"

    @pytest.mark.asyncio
    async def test_list_models(self, llm_model_repository: LLMModelRepository):
        """Test listing LLM models."""
        # Arrange
        model1 = create_test_llm_model(name="Model 1")
        model2 = create_test_llm_model(name="Model 2")

        await llm_model_repository.create(model1)
        await llm_model_repository.create(model2)

        # Act
        models = await llm_model_repository.list()

        # Assert
        assert len(models) == 2
        model_names = [model.name for model in models]
        assert "Model 1" in model_names
        assert "Model 2" in model_names

    @pytest.mark.asyncio
    async def test_update_model(self, llm_model_repository: LLMModelRepository):
        """Test updating an LLM model."""
        # Arrange
        model = create_test_llm_model(name="Original Name")
        created_model = await llm_model_repository.create(model)

        # Modify
        created_model.name = "Updated Name"
        created_model.description = "Updated description"

        # Act
        updated_model = await llm_model_repository.update(created_model)

        # Assert
        assert updated_model.name == "Updated Name"
        assert updated_model.description == "Updated description"

        # Verify persistence
        retrieved_model = await llm_model_repository.get(created_model.id)
        assert retrieved_model.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_model(self, llm_model_repository: LLMModelRepository):
        """Test deleting an LLM model."""
        # Arrange
        model = create_test_llm_model()
        created_model = await llm_model_repository.create(model)

        # Act
        delete_result = await llm_model_repository.delete(created_model.id)

        # Assert
        assert delete_result is True

        # Verify deletion
        deleted_model = await llm_model_repository.get(created_model.id)
        assert deleted_model is None

    @pytest.mark.asyncio
    async def test_get_nonexistent_model(self, llm_model_repository: LLMModelRepository):
        """Test getting a non-existent model returns None."""
        # Act
        result = await llm_model_repository.get(uuid4())

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_model(self, llm_model_repository: LLMModelRepository):
        """Test deleting a non-existent model returns False."""
        # Act
        result = await llm_model_repository.delete(uuid4())

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_model_with_different_statuses(self, llm_model_repository: LLMModelRepository):
        """Test creating models with different statuses."""
        # Arrange
        statuses = ["active", "inactive", "draft"]

        for status in statuses:
            model = create_test_llm_model(name=f"Model {status}", status=status)

            # Act
            created_model = await llm_model_repository.create(model)

            # Assert
            assert created_model.status == status

            # Verify persistence
            retrieved_model = await llm_model_repository.get(created_model.id)
            assert retrieved_model.status == status

    @pytest.mark.asyncio
    async def test_model_with_different_types(self, llm_model_repository: LLMModelRepository):
        """Test creating models with different types."""
        # Arrange
        model_types = ["chat", "completion", "embedding"]

        for model_type in model_types:
            model = create_test_llm_model(name=f"Model {model_type}", model_type=model_type)

            # Act
            created_model = await llm_model_repository.create(model)

            # Assert
            assert created_model.model_type == model_type

            # Verify persistence
            retrieved_model = await llm_model_repository.get(created_model.id)
            assert retrieved_model.model_type == model_type

    @pytest.mark.asyncio
    async def test_public_private_models(self, llm_model_repository: LLMModelRepository):
        """Test creating public and private models."""
        # Arrange
        public_model = create_test_llm_model(name="Public Model", is_public=True)
        private_model = create_test_llm_model(name="Private Model", is_public=False)

        # Act
        created_public = await llm_model_repository.create(public_model)
        created_private = await llm_model_repository.create(private_model)

        # Assert
        assert created_public.is_public is True
        assert created_private.is_public is False

        # Verify both models exist
        models = await llm_model_repository.list()
        assert len(models) == 2

        public_flags = [model.is_public for model in models]
        assert True in public_flags
        assert False in public_flags

    @pytest.mark.asyncio
    async def test_model_provider_relationship(self, llm_model_repository: LLMModelRepository):
        """Test models with different provider IDs."""
        # Arrange
        provider_id_1 = uuid4()
        provider_id_2 = uuid4()

        model1 = create_test_llm_model(provider_id=provider_id_1, name="Model 1")
        model2 = create_test_llm_model(provider_id=provider_id_2, name="Model 2")

        # Act
        created_model1 = await llm_model_repository.create(model1)
        created_model2 = await llm_model_repository.create(model2)

        # Assert
        assert created_model1.provider_id == provider_id_1
        assert created_model2.provider_id == provider_id_2

        # Verify both models exist
        models = await llm_model_repository.list()
        assert len(models) == 2

        provider_ids = [model.provider_id for model in models]
        assert provider_id_1 in provider_ids
        assert provider_id_2 in provider_ids
