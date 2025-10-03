"""
Integration tests for ProviderSpecRepository - new 4-entity architecture.
"""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from agentarea_common.base.models import BaseModel
from agentarea_llm.domain.models import ProviderSpec
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
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
async def provider_spec_repository(db_session):
    """Provide a ProviderSpecRepository instance."""
    return ProviderSpecRepository(db_session)


def create_test_provider_spec(**kwargs) -> ProviderSpec:
    """Create a test provider spec with default values."""
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


class TestProviderSpecRepository:
    """Test cases for ProviderSpecRepository."""

    @pytest.mark.asyncio
    async def test_create_and_get_provider_spec(
        self, provider_spec_repository: ProviderSpecRepository
    ):
        """Test creating and retrieving a provider spec."""
        # Arrange
        provider_spec = create_test_provider_spec(
            provider_key="openai", name="OpenAI", provider_type="openai"
        )

        # Act - Create
        created_spec = await provider_spec_repository.create(provider_spec)

        # Assert - Create
        assert created_spec is not None
        assert created_spec.provider_key == "openai"
        assert created_spec.name == "OpenAI"
        assert created_spec.provider_type == "openai"

        # Act - Get
        retrieved_spec = await provider_spec_repository.get(created_spec.id)

        # Assert - Get
        assert retrieved_spec is not None
        assert retrieved_spec.id == created_spec.id
        assert retrieved_spec.provider_key == "openai"

    @pytest.mark.asyncio
    async def test_get_by_provider_key(self, provider_spec_repository: ProviderSpecRepository):
        """Test getting provider spec by provider key."""
        # Arrange
        provider_spec = create_test_provider_spec(
            provider_key="anthropic", name="Anthropic", provider_type="anthropic"
        )
        await provider_spec_repository.create(provider_spec)

        # Act
        retrieved_spec = await provider_spec_repository.get_by_provider_key("anthropic")

        # Assert
        assert retrieved_spec is not None
        assert retrieved_spec.provider_key == "anthropic"
        assert retrieved_spec.name == "Anthropic"

    @pytest.mark.asyncio
    async def test_list_provider_specs(self, provider_spec_repository: ProviderSpecRepository):
        """Test listing provider specs."""
        # Arrange
        spec1 = create_test_provider_spec(provider_key="openai", name="OpenAI")
        spec2 = create_test_provider_spec(provider_key="anthropic", name="Anthropic")

        await provider_spec_repository.create(spec1)
        await provider_spec_repository.create(spec2)

        # Act
        specs = await provider_spec_repository.list()

        # Assert
        assert len(specs) == 2
        provider_keys = [spec.provider_key for spec in specs]
        assert "openai" in provider_keys
        assert "anthropic" in provider_keys

    @pytest.mark.asyncio
    async def test_list_builtin_specs(self, provider_spec_repository: ProviderSpecRepository):
        """Test listing only builtin provider specs."""
        # Arrange
        builtin_spec = create_test_provider_spec(
            provider_key="openai", name="OpenAI", is_builtin=True
        )
        custom_spec = create_test_provider_spec(
            provider_key="custom", name="Custom Provider", is_builtin=False
        )

        await provider_spec_repository.create(builtin_spec)
        await provider_spec_repository.create(custom_spec)

        # Act
        builtin_specs = await provider_spec_repository.list(is_builtin=True)

        # Assert
        assert len(builtin_specs) == 1
        assert builtin_specs[0].provider_key == "openai"
        assert builtin_specs[0].is_builtin is True

    @pytest.mark.asyncio
    async def test_update_provider_spec(self, provider_spec_repository: ProviderSpecRepository):
        """Test updating a provider spec."""
        # Arrange
        provider_spec = create_test_provider_spec(
            provider_key="openai", name="OpenAI", description="Original description"
        )
        created_spec = await provider_spec_repository.create(provider_spec)

        # Modify
        created_spec.name = "OpenAI Updated"
        created_spec.description = "Updated description"

        # Act
        updated_spec = await provider_spec_repository.update(created_spec)

        # Assert
        assert updated_spec.name == "OpenAI Updated"
        assert updated_spec.description == "Updated description"

        # Verify persistence
        retrieved_spec = await provider_spec_repository.get(created_spec.id)
        assert retrieved_spec.name == "OpenAI Updated"

    @pytest.mark.asyncio
    async def test_delete_provider_spec(self, provider_spec_repository: ProviderSpecRepository):
        """Test deleting a provider spec."""
        # Arrange
        provider_spec = create_test_provider_spec()
        created_spec = await provider_spec_repository.create(provider_spec)

        # Act
        delete_result = await provider_spec_repository.delete(created_spec.id)

        # Assert
        assert delete_result is True

        # Verify deletion
        deleted_spec = await provider_spec_repository.get(created_spec.id)
        assert deleted_spec is None

    @pytest.mark.asyncio
    async def test_upsert_by_provider_key_create(
        self, provider_spec_repository: ProviderSpecRepository
    ):
        """Test upserting a new provider spec by provider key."""
        # Arrange
        provider_spec = create_test_provider_spec(provider_key="new_provider", name="New Provider")

        # Act
        upserted_spec = await provider_spec_repository.upsert_by_provider_key(provider_spec)

        # Assert
        assert upserted_spec is not None
        assert upserted_spec.provider_key == "new_provider"
        assert upserted_spec.name == "New Provider"

        # Verify it was created
        retrieved_spec = await provider_spec_repository.get_by_provider_key("new_provider")
        assert retrieved_spec is not None

    @pytest.mark.asyncio
    async def test_upsert_by_provider_key_update(
        self, provider_spec_repository: ProviderSpecRepository
    ):
        """Test upserting an existing provider spec by provider key."""
        # Arrange - Create initial spec
        initial_spec = create_test_provider_spec(
            provider_key="existing_provider", name="Initial Name", description="Initial description"
        )
        await provider_spec_repository.create(initial_spec)

        # Create updated spec with same provider key
        updated_spec = create_test_provider_spec(
            provider_key="existing_provider",  # Same key
            name="Updated Name",
            description="Updated description",
        )

        # Act
        upserted_spec = await provider_spec_repository.upsert_by_provider_key(updated_spec)

        # Assert
        assert upserted_spec.provider_key == "existing_provider"
        assert upserted_spec.name == "Updated Name"
        assert upserted_spec.description == "Updated description"

        # Verify only one record exists
        all_specs = await provider_spec_repository.list()
        existing_specs = [s for s in all_specs if s.provider_key == "existing_provider"]
        assert len(existing_specs) == 1

    @pytest.mark.asyncio
    async def test_get_nonexistent_spec(self, provider_spec_repository: ProviderSpecRepository):
        """Test getting a non-existent provider spec returns None."""
        # Act
        result = await provider_spec_repository.get(uuid4())

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_nonexistent_key(self, provider_spec_repository: ProviderSpecRepository):
        """Test getting by non-existent provider key returns None."""
        # Act
        result = await provider_spec_repository.get_by_provider_key("nonexistent")

        # Assert
        assert result is None


@pytest.mark.asyncio
async def test_provider_spec_repository_with_populated_data(populated_db_session):
    """Test that the populated database fixture works correctly."""
    repo = ProviderSpecRepository(populated_db_session)

    # Check that Ollama provider spec exists
    ollama_spec = await repo.get(UUID("183a5efc-2525-4a1e-aded-1a5d5e9ff13b"))
    assert ollama_spec is not None
    assert ollama_spec.provider_key == "ollama"
    assert ollama_spec.name == "Ollama"
    assert ollama_spec.provider_type == "ollama_chat"

    # Check that we can find it by provider key
    ollama_by_key = await repo.get_by_provider_key("ollama")
    assert ollama_by_key is not None
    assert ollama_by_key.id == ollama_spec.id

    # Check that all specs are retrievable
    all_specs = await repo.list()
    assert len(all_specs) >= 1
    assert any(spec.provider_key == "ollama" for spec in all_specs)


@pytest.mark.asyncio
async def test_provider_spec_repository_create(populated_db_session):
    """Test creating a new provider spec."""
    repo = ProviderSpecRepository(populated_db_session)

    # Create a new provider spec
    new_spec = ProviderSpec(
        provider_key="test-provider",
        name="Test Provider",
        description="A test provider",
        provider_type="test",
        icon="test",
        is_builtin=False,
    )

    created_spec = await repo.create(new_spec)
    assert created_spec.id is not None
    assert created_spec.provider_key == "test-provider"
    assert created_spec.name == "Test Provider"

    # Verify it can be retrieved
    retrieved_spec = await repo.get(created_spec.id)
    assert retrieved_spec is not None
    assert retrieved_spec.provider_key == "test-provider"
