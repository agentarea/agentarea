"""
Integration tests for ModelInstanceRepository - new 4-entity architecture.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_common.base.models import BaseModel
from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
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
async def model_instance_repository(db_session):
    """Provide a ModelInstanceRepository instance."""
    return ModelInstanceRepository(db_session)


def create_test_provider_spec(**kwargs) -> ProviderSpec:
    """Create a test provider spec."""
    defaults = {
        "id": uuid4(),
        "provider_key": f"test-provider-{uuid4().hex[:8]}",
        "name": f"Test Provider {uuid4().hex[:8]}",
        "description": "Test provider description",
        "provider_type": "test_provider",
        "icon": "test_icon",
        "is_builtin": True,
    }
    defaults.update(kwargs)
    return ProviderSpec(**defaults)


def create_test_provider_config(provider_spec_id, **kwargs) -> ProviderConfig:
    """Create a test provider config."""
    defaults = {
        "id": uuid4(),
        "provider_spec_id": provider_spec_id,
        "name": f"Test Config {uuid4().hex[:8]}",
        "api_key": "test-api-key",
        "endpoint_url": None,
        "workspace_id": "default",
        "created_by": "system",
        "is_active": True,
        "is_public": False,
    }
    defaults.update(kwargs)
    return ProviderConfig(**defaults)


def create_test_model_spec(provider_spec_id, **kwargs) -> ModelSpec:
    """Create a test model spec."""
    defaults = {
        "id": uuid4(),
        "provider_spec_id": provider_spec_id,
        "model_name": f"test-model-{uuid4().hex[:8]}",
        "display_name": f"Test Model {uuid4().hex[:8]}",
        "description": "Test model description",
        "context_window": 4096,
        "is_active": True,
    }
    defaults.update(kwargs)
    return ModelSpec(**defaults)


def create_test_model_instance(provider_config_id, model_spec_id, **kwargs) -> ModelInstance:
    """Create a test model instance."""
    defaults = {
        "id": uuid4(),
        "provider_config_id": provider_config_id,
        "model_spec_id": model_spec_id,
        "name": f"Test Instance {uuid4().hex[:8]}",
        "description": "Test instance description",
        "is_active": True,
        "is_public": False,
    }
    defaults.update(kwargs)
    return ModelInstance(**defaults)


class TestModelInstanceRepository:
    """Test cases for ModelInstanceRepository."""

    @pytest.mark.asyncio
    async def test_create_and_get_model_instance(
        self, db_session: AsyncSession, model_instance_repository: ModelInstanceRepository
    ):
        """Test creating and retrieving a model instance."""
        # Arrange - Create dependencies
        provider_spec = create_test_provider_spec(provider_key="openai", name="OpenAI")
        db_session.add(provider_spec)
        await db_session.flush()

        provider_config = create_test_provider_config(provider_spec.id, name="My OpenAI Config")
        db_session.add(provider_config)
        await db_session.flush()

        model_spec = create_test_model_spec(
            provider_spec.id, model_name="gpt-4", display_name="GPT-4"
        )
        db_session.add(model_spec)
        await db_session.flush()

        # Create model instance
        model_instance = create_test_model_instance(
            provider_config.id, model_spec.id, name="My GPT-4 Instance"
        )

        # Act - Create
        created_instance = await model_instance_repository.create(model_instance)

        # Assert - Create
        assert created_instance is not None
        assert created_instance.name == "My GPT-4 Instance"
        assert created_instance.provider_config_id == provider_config.id
        assert created_instance.model_spec_id == model_spec.id

        # Act - Get
        retrieved_instance = await model_instance_repository.get(created_instance.id)

        # Assert - Get
        assert retrieved_instance is not None
        assert retrieved_instance.id == created_instance.id
        assert retrieved_instance.name == "My GPT-4 Instance"

    @pytest.mark.asyncio
    async def test_list_model_instances(
        self, db_session: AsyncSession, model_instance_repository: ModelInstanceRepository
    ):
        """Test listing model instances."""
        # Arrange - Create dependencies
        provider_spec = create_test_provider_spec()
        db_session.add(provider_spec)
        await db_session.flush()

        provider_config = create_test_provider_config(provider_spec.id)
        db_session.add(provider_config)
        await db_session.flush()

        model_spec = create_test_model_spec(provider_spec.id)
        db_session.add(model_spec)
        await db_session.flush()

        # Create multiple instances
        instance1 = create_test_model_instance(provider_config.id, model_spec.id, name="Instance 1")
        instance2 = create_test_model_instance(provider_config.id, model_spec.id, name="Instance 2")

        await model_instance_repository.create(instance1)
        await model_instance_repository.create(instance2)

        # Act
        instances = await model_instance_repository.list()

        # Assert
        assert len(instances) == 2
        instance_names = [instance.name for instance in instances]
        assert "Instance 1" in instance_names
        assert "Instance 2" in instance_names

    @pytest.mark.asyncio
    async def test_list_by_provider_config(
        self, db_session: AsyncSession, model_instance_repository: ModelInstanceRepository
    ):
        """Test listing model instances by provider config."""
        # Arrange
        provider_spec = create_test_provider_spec()
        db_session.add(provider_spec)
        await db_session.flush()

        config1 = create_test_provider_config(provider_spec.id, name="Config 1")
        config2 = create_test_provider_config(provider_spec.id, name="Config 2")
        db_session.add_all([config1, config2])
        await db_session.flush()

        model_spec = create_test_model_spec(provider_spec.id)
        db_session.add(model_spec)
        await db_session.flush()

        # Create instances for different configs
        instance1 = create_test_model_instance(config1.id, model_spec.id, name="Config1 Instance")
        instance2 = create_test_model_instance(config2.id, model_spec.id, name="Config2 Instance")

        await model_instance_repository.create(instance1)
        await model_instance_repository.create(instance2)

        # Act
        config1_instances = await model_instance_repository.list(provider_config_id=config1.id)

        # Assert
        assert len(config1_instances) == 1
        assert config1_instances[0].name == "Config1 Instance"
        assert config1_instances[0].provider_config_id == config1.id

    @pytest.mark.asyncio
    async def test_list_by_model_spec(
        self, db_session: AsyncSession, model_instance_repository: ModelInstanceRepository
    ):
        """Test listing model instances by model spec."""
        # Arrange
        provider_spec = create_test_provider_spec()
        db_session.add(provider_spec)
        await db_session.flush()

        provider_config = create_test_provider_config(provider_spec.id)
        db_session.add(provider_config)
        await db_session.flush()

        model_spec1 = create_test_model_spec(provider_spec.id, model_name="gpt-4")
        model_spec2 = create_test_model_spec(provider_spec.id, model_name="gpt-3.5")
        db_session.add_all([model_spec1, model_spec2])
        await db_session.flush()

        # Create instances for different model specs
        instance1 = create_test_model_instance(
            provider_config.id, model_spec1.id, name="GPT-4 Instance"
        )
        instance2 = create_test_model_instance(
            provider_config.id, model_spec2.id, name="GPT-3.5 Instance"
        )

        await model_instance_repository.create(instance1)
        await model_instance_repository.create(instance2)

        # Act
        gpt4_instances = await model_instance_repository.list(model_spec_id=model_spec1.id)

        # Assert
        assert len(gpt4_instances) == 1
        assert gpt4_instances[0].name == "GPT-4 Instance"
        assert gpt4_instances[0].model_spec_id == model_spec1.id

    @pytest.mark.asyncio
    async def test_update_model_instance(
        self, db_session: AsyncSession, model_instance_repository: ModelInstanceRepository
    ):
        """Test updating a model instance."""
        # Arrange
        provider_spec = create_test_provider_spec()
        db_session.add(provider_spec)
        await db_session.flush()

        provider_config = create_test_provider_config(provider_spec.id)
        db_session.add(provider_config)
        await db_session.flush()

        model_spec = create_test_model_spec(provider_spec.id)
        db_session.add(model_spec)
        await db_session.flush()

        model_instance = create_test_model_instance(
            provider_config.id, model_spec.id, name="Original Name"
        )
        created_instance = await model_instance_repository.create(model_instance)

        # Modify
        created_instance.name = "Updated Name"
        created_instance.description = "Updated description"

        # Act
        updated_instance = await model_instance_repository.update(created_instance)

        # Assert
        assert updated_instance.name == "Updated Name"
        assert updated_instance.description == "Updated description"

        # Verify persistence
        retrieved_instance = await model_instance_repository.get(created_instance.id)
        assert retrieved_instance.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_model_instance(
        self, db_session: AsyncSession, model_instance_repository: ModelInstanceRepository
    ):
        """Test deleting a model instance."""
        # Arrange
        provider_spec = create_test_provider_spec()
        db_session.add(provider_spec)
        await db_session.flush()

        provider_config = create_test_provider_config(provider_spec.id)
        db_session.add(provider_config)
        await db_session.flush()

        model_spec = create_test_model_spec(provider_spec.id)
        db_session.add(model_spec)
        await db_session.flush()

        model_instance = create_test_model_instance(provider_config.id, model_spec.id)
        created_instance = await model_instance_repository.create(model_instance)

        # Act
        delete_result = await model_instance_repository.delete(created_instance.id)

        # Assert
        assert delete_result is True

        # Verify deletion
        deleted_instance = await model_instance_repository.get(created_instance.id)
        assert deleted_instance is None

    @pytest.mark.asyncio
    async def test_list_active_instances(
        self, db_session: AsyncSession, model_instance_repository: ModelInstanceRepository
    ):
        """Test listing only active model instances."""
        # Arrange
        provider_spec = create_test_provider_spec()
        db_session.add(provider_spec)
        await db_session.flush()

        provider_config = create_test_provider_config(provider_spec.id)
        db_session.add(provider_config)
        await db_session.flush()

        model_spec = create_test_model_spec(provider_spec.id)
        db_session.add(model_spec)
        await db_session.flush()

        # Create active and inactive instances
        active_instance = create_test_model_instance(
            provider_config.id, model_spec.id, name="Active Instance", is_active=True
        )
        inactive_instance = create_test_model_instance(
            provider_config.id, model_spec.id, name="Inactive Instance", is_active=False
        )

        await model_instance_repository.create(active_instance)
        await model_instance_repository.create(inactive_instance)

        # Act
        active_instances = await model_instance_repository.list(is_active=True)

        # Assert
        assert len(active_instances) == 1
        assert active_instances[0].name == "Active Instance"
        assert active_instances[0].is_active is True
