"""
Simple integration tests for LLMModelInstanceRepository.

Tests all CRUD operations and relationship handling on the LLMModelInstanceRepository.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from agentarea_llm.domain.models import LLMModel, LLMModelInstance, LLMProvider
from agentarea_llm.infrastructure.llm_model_instance_repository import (
    LLMModelInstanceRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TestLLMModelInstanceRepository:
    """Test cases for LLMModelInstanceRepository."""

    def create_test_provider(self, name: str = "Test Provider") -> LLMProvider:
        """Create a test LLMProvider with UUID objects."""
        return LLMProvider(
            id=uuid4(),
            name=name,
            description=f"{name} description",
            provider_type=name.lower().replace(" ", "_"),
            is_builtin=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def create_test_model(self, provider_id: UUID, name: str = "Test Model") -> LLMModel:
        """Create a test LLMModel with UUID objects."""
        return LLMModel(
            id=uuid4(),
            name=name,
            description=f"{name} description",
            provider_id=provider_id,
            model_type="chat",
            endpoint_url="http://host.docker.internal:11434",
            context_window="8192",
            status="active",
            is_public=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def create_test_instance(
        self,
        model_id: UUID,
        name: str = "Test Instance",
        description: str = "Test instance description",
        api_key: str = "test-api-key",
        status: str = "active",
        is_public: bool = False,
    ) -> LLMModelInstance:
        """Create a test LLMModelInstance with UUID objects."""
        return LLMModelInstance(
            id=uuid4(),
            model_id=model_id,
            name=name,
            description=description,
            api_key=api_key,
            status=status,
            is_public=is_public,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    @pytest.mark.asyncio
    async def test_create_and_get_instance(self, db_session: AsyncSession, model_factory):
        """Test creating and retrieving an LLM model instance."""
        repository = LLMModelInstanceRepository(db_session)

        # Create provider with UUID object (not string)
        provider = LLMProvider(
            id=uuid4(),
            name="Test Provider",
            description="Test LLM provider",
            provider_type="test",
            is_builtin=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(provider)
        await db_session.flush()

        # Create model with UUID object
        model = LLMModel(
            id=uuid4(),
            name="Test Model",
            description="Test LLM model",
            provider_id=provider.id,
            model_type="chat",
            endpoint_url="http://host.docker.internal:11434",
            context_window="8192",
            status="active",
            is_public=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(model)
        await db_session.flush()

        # Create instance with UUID object
        instance = LLMModelInstance(
            id=uuid4(),
            model_id=model.id,
            name="GPT-4 Instance",
            description="Production GPT-4 instance",
            api_key="sk-test-key-123",
            status="active",
            is_public=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        created_instance = await repository.create(instance)

        assert created_instance is not None
        assert created_instance.id == instance.id
        assert created_instance.name == "GPT-4 Instance"
        assert created_instance.description == "Production GPT-4 instance"
        assert created_instance.api_key == "sk-test-key-123"
        assert created_instance.model_id == model.id
        assert created_instance.status == "active"
        assert created_instance.is_public is False

        # Test retrieval
        retrieved_instance = await repository.get(created_instance.id)

        assert retrieved_instance is not None
        assert retrieved_instance.id == created_instance.id
        assert retrieved_instance.name == "GPT-4 Instance"
        assert retrieved_instance.model_id == model.id

    @pytest.mark.asyncio
    async def test_list_instances(self, db_session: AsyncSession, model_factory):
        """Test listing LLM model instances."""
        repository = LLMModelInstanceRepository(db_session)

        # Create provider and model with UUID objects
        provider = LLMProvider(
            id=uuid4(),
            name="OpenAI",
            description="OpenAI provider",
            provider_type="openai",
            is_builtin=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(provider)
        await db_session.flush()

        model = LLMModel(
            id=uuid4(),
            name="GPT-4",
            description="GPT-4 model",
            provider_id=provider.id,
            model_type="chat",
            endpoint_url="http://host.docker.internal:11434",
            context_window="8192",
            status="active",
            is_public=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(model)
        await db_session.flush()

        # Create multiple instances
        instance1 = LLMModelInstance(
            id=uuid4(),
            model_id=model.id,
            name="GPT-4 Production",
            description="Production instance",
            api_key="test-key-1",
            status="active",
            is_public=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        instance2 = LLMModelInstance(
            id=uuid4(),
            model_id=model.id,
            name="GPT-4 Testing",
            description="Testing instance",
            api_key="test-key-2",
            status="inactive",
            is_public=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        await repository.create(instance1)
        await repository.create(instance2)

        instances = await repository.list()

        assert len(instances) >= 2
        instance_names = [instance.name for instance in instances]
        assert "GPT-4 Production" in instance_names
        assert "GPT-4 Testing" in instance_names

    @pytest.mark.asyncio
    async def test_update_instance(self, db_session: AsyncSession, model_factory):
        """Test updating an existing LLM model instance."""
        repository = LLMModelInstanceRepository(db_session)

        # Create provider and model with UUID objects
        provider = self.create_test_provider(name="Anthropic")
        db_session.add(provider)
        await db_session.flush()

        model = self.create_test_model(provider_id=provider.id, name="Claude")
        db_session.add(model)
        await db_session.flush()

        # Create instance
        instance = self.create_test_instance(
            model_id=model.id,
            name="Claude Original",
            description="Original description",
            status="inactive",
        )

        created_instance = await repository.create(instance)

        # Update the instance
        created_instance.name = "Claude Updated"
        created_instance.description = "Updated description"
        created_instance.status = "active"

        updated_instance = await repository.update(created_instance)

        assert updated_instance.name == "Claude Updated"
        assert updated_instance.description == "Updated description"
        assert updated_instance.status == "active"

        # Verify the update persisted
        retrieved_instance = await repository.get(created_instance.id)
        assert retrieved_instance.name == "Claude Updated"
        assert retrieved_instance.status == "active"

    @pytest.mark.asyncio
    async def test_delete_instance(self, db_session: AsyncSession, model_factory):
        """Test deleting an LLM model instance."""
        repository = LLMModelInstanceRepository(db_session)

        # Create provider and model with UUID objects
        provider = self.create_test_provider(name="Google")
        db_session.add(provider)
        await db_session.flush()

        model = self.create_test_model(provider_id=provider.id, name="Gemini")
        db_session.add(model)
        await db_session.flush()

        # Create instance
        instance = self.create_test_instance(model_id=model.id, name="Gemini Instance")

        created_instance = await repository.create(instance)

        # Delete the instance
        delete_result = await repository.delete(created_instance.id)
        assert delete_result is True

        # Verify it's deleted
        retrieved_instance = await repository.get(created_instance.id)
        assert retrieved_instance is None

    @pytest.mark.asyncio
    async def test_get_nonexistent_instance(self, db_session: AsyncSession):
        """Test retrieving a non-existent instance returns None."""
        repository = LLMModelInstanceRepository(db_session)

        nonexistent_id = uuid4()
        result = await repository.get(nonexistent_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_instance(self, db_session: AsyncSession):
        """Test deleting a non-existent instance returns False."""
        repository = LLMModelInstanceRepository(db_session)

        nonexistent_id = uuid4()
        result = await repository.delete(nonexistent_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_list_instances_by_model_id(self, db_session: AsyncSession, model_factory):
        """Test filtering instances by model_id."""
        repository = LLMModelInstanceRepository(db_session)

        # Create provider and two models with UUID objects
        provider = self.create_test_provider(name="OpenAI")
        db_session.add(provider)
        await db_session.flush()

        model1 = self.create_test_model(provider_id=provider.id, name="GPT-4")
        model2 = self.create_test_model(provider_id=provider.id, name="GPT-3.5")
        db_session.add(model1)
        db_session.add(model2)
        await db_session.flush()

        # Create instances for different models
        instance1 = self.create_test_instance(model_id=model1.id, name="GPT-4 Instance 1")
        instance2 = self.create_test_instance(model_id=model1.id, name="GPT-4 Instance 2")
        instance3 = self.create_test_instance(model_id=model2.id, name="GPT-3.5 Instance")

        await repository.create(instance1)
        await repository.create(instance2)
        await repository.create(instance3)

        # Filter by model1.id
        model1_instances = await repository.list(model_id=model1.id)

        assert len(model1_instances) == 2
        instance_names = [instance.name for instance in model1_instances]
        assert "GPT-4 Instance 1" in instance_names
        assert "GPT-4 Instance 2" in instance_names
        assert "GPT-3.5 Instance" not in instance_names

    @pytest.mark.asyncio
    async def test_list_instances_by_status(self, db_session: AsyncSession, model_factory):
        """Test filtering instances by status."""
        repository = LLMModelInstanceRepository(db_session)

        # Create provider and model with UUID objects
        provider = self.create_test_provider(name="Cohere")
        db_session.add(provider)
        await db_session.flush()

        model = self.create_test_model(provider_id=provider.id, name="Command")
        db_session.add(model)
        await db_session.flush()

        # Create instances with different statuses
        active_instance = self.create_test_instance(
            model_id=model.id, name="Active Instance", status="active"
        )
        inactive_instance = self.create_test_instance(
            model_id=model.id, name="Inactive Instance", status="inactive"
        )
        pending_instance = self.create_test_instance(
            model_id=model.id, name="Pending Instance", status="pending"
        )

        await repository.create(active_instance)
        await repository.create(inactive_instance)
        await repository.create(pending_instance)

        # Filter by active status
        active_instances = await repository.list(status="active")
        active_names = [instance.name for instance in active_instances]
        assert "Active Instance" in active_names
        assert "Inactive Instance" not in active_names
        assert "Pending Instance" not in active_names

    @pytest.mark.asyncio
    async def test_list_instances_by_public_status(self, db_session: AsyncSession, model_factory):
        """Test filtering instances by public/private status."""
        repository = LLMModelInstanceRepository(db_session)

        # Create provider and model with UUID objects
        provider = self.create_test_provider(name="Hugging Face")
        db_session.add(provider)
        await db_session.flush()

        model = self.create_test_model(provider_id=provider.id, name="BERT")
        db_session.add(model)
        await db_session.flush()

        # Create public and private instances
        public_instance = self.create_test_instance(
            model_id=model.id, name="Public Instance", is_public=True
        )
        private_instance = self.create_test_instance(
            model_id=model.id, name="Private Instance", is_public=False
        )

        await repository.create(public_instance)
        await repository.create(private_instance)

        # Filter by public instances
        public_instances = await repository.list(is_public=True)
        public_names = [instance.name for instance in public_instances]
        assert "Public Instance" in public_names
        assert "Private Instance" not in public_names

        # Filter by private instances
        private_instances = await repository.list(is_public=False)
        private_names = [instance.name for instance in private_instances]
        assert "Private Instance" in private_names
        assert "Public Instance" not in private_names

    @pytest.mark.asyncio
    async def test_complex_filtering(self, db_session: AsyncSession, model_factory):
        """Test filtering instances with multiple criteria."""
        repository = LLMModelInstanceRepository(db_session)

        # Create provider and model with UUID objects
        provider = self.create_test_provider(name="Stability AI")
        db_session.add(provider)
        await db_session.flush()

        model = self.create_test_model(provider_id=provider.id, name="Stable Diffusion")
        db_session.add(model)
        await db_session.flush()

        # Create various instances
        target_instance = self.create_test_instance(
            model_id=model.id, name="Target Instance", status="active", is_public=True
        )
        non_matching1 = self.create_test_instance(
            model_id=model.id,
            name="Non-matching 1",
            status="inactive",  # Different status
            is_public=True,
        )
        non_matching2 = self.create_test_instance(
            model_id=model.id,
            name="Non-matching 2",
            status="active",
            is_public=False,  # Different public status
        )

        await repository.create(target_instance)
        await repository.create(non_matching1)
        await repository.create(non_matching2)

        # Filter with multiple criteria
        filtered_instances = await repository.list(
            model_id=model.id, status="active", is_public=True
        )

        assert len(filtered_instances) == 1
        assert filtered_instances[0].name == "Target Instance"

    @pytest.mark.asyncio
    async def test_instance_model_relationship(self, db_session: AsyncSession, model_factory):
        """Test that instance-model relationships are properly loaded."""
        repository = LLMModelInstanceRepository(db_session)

        # Create provider and model with UUID objects
        provider = self.create_test_provider(name="DeepMind")
        db_session.add(provider)
        await db_session.flush()

        model = self.create_test_model(provider_id=provider.id, name="Gemini Pro")
        db_session.add(model)
        await db_session.flush()

        # Create instance
        instance = self.create_test_instance(model_id=model.id, name="Gemini Pro Instance")

        created_instance = await repository.create(instance)

        # Retrieve with relationship
        retrieved_instance = await repository.get(created_instance.id)

        assert retrieved_instance is not None
        assert retrieved_instance.model is not None
        assert retrieved_instance.model.name == "Gemini Pro"
        assert retrieved_instance.model.description == "Gemini Pro description"
        assert retrieved_instance.model.provider_id == provider.id
