"""
Test that provider specs are correctly populated for integration tests.
"""

from uuid import UUID, uuid4

import pytest
from agentarea_llm.domain.models import ModelSpec, ProviderSpec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_OLLAMA_PROVIDER_ID = UUID("183a5efc-2525-4a1e-aded-1a5d5e9ff13b")


@pytest.fixture
async def populated_db_session(db_session: AsyncSession) -> AsyncSession:
    """Populate the (in-memory) test db_session with an Ollama provider + models."""
    ollama_provider = ProviderSpec(
        id=_OLLAMA_PROVIDER_ID,
        provider_key="ollama",
        name="Ollama",
        description="Local and open source models through Ollama",
        provider_type="ollama_chat",
        icon="ollama",
        is_builtin=True,
        workspace_id="default",
        created_by="system",
    )
    db_session.add(ollama_provider)

    model_specs = [
        ModelSpec(
            id=uuid4(),
            provider_spec_id=_OLLAMA_PROVIDER_ID,
            model_name="qwen2.5",
            display_name="Qwen 2.5",
            description="Alibaba's Qwen 2.5 model",
            context_window=8192,
            is_active=True,
            workspace_id="default",
            created_by="system",
        ),
        ModelSpec(
            id=uuid4(),
            provider_spec_id=_OLLAMA_PROVIDER_ID,
            model_name="llama2",
            display_name="Llama 2",
            description="Meta's Llama 2 model",
            context_window=4096,
            is_active=True,
            workspace_id="default",
            created_by="system",
        ),
        ModelSpec(
            id=uuid4(),
            provider_spec_id=_OLLAMA_PROVIDER_ID,
            model_name="mistral",
            display_name="Mistral",
            description="Mistral's open source model",
            context_window=8192,
            is_active=True,
            workspace_id="default",
            created_by="system",
        ),
    ]
    for model_spec in model_specs:
        db_session.add(model_spec)

    await db_session.commit()

    return db_session


@pytest.mark.asyncio
async def test_provider_specs_populated(populated_db_session: AsyncSession):
    """Test that provider specs are populated correctly in the test database."""

    # Check that Ollama provider spec exists
    result = await populated_db_session.execute(
        select(ProviderSpec).where(ProviderSpec.provider_key == "ollama")
    )
    ollama_provider = result.scalar_one_or_none()

    assert ollama_provider is not None
    assert ollama_provider.name == "Ollama"
    assert ollama_provider.provider_type == "ollama_chat"
    assert ollama_provider.provider_key == "ollama"


@pytest.mark.asyncio
async def test_model_specs_populated(populated_db_session: AsyncSession):
    """Test that model specs are populated correctly for Ollama."""

    # Get Ollama provider
    result = await populated_db_session.execute(
        select(ProviderSpec).where(ProviderSpec.provider_key == "ollama")
    )
    ollama_provider = result.scalar_one_or_none()
    assert ollama_provider is not None

    # Check that qwen model exists
    result = await populated_db_session.execute(
        select(ModelSpec).where(
            ModelSpec.provider_spec_id == ollama_provider.id, ModelSpec.model_name == "qwen2.5"
        )
    )
    qwen_model = result.scalar_one_or_none()

    assert qwen_model is not None
    assert qwen_model.display_name == "Qwen 2.5"
    assert qwen_model.context_window == 8192
    assert qwen_model.is_active is True

    # Check that all Ollama models exist
    result = await populated_db_session.execute(
        select(ModelSpec).where(ModelSpec.provider_spec_id == ollama_provider.id)
    )
    ollama_models = result.scalars().all()

    assert len(ollama_models) >= 3  # qwen, llama, mistral
    model_names = [model.model_name for model in ollama_models]
    assert "qwen2.5" in model_names
    assert "llama2" in model_names
    assert "mistral" in model_names
