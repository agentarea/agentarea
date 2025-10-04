"""
Test that provider specs are correctly populated for integration tests.
"""

import pytest
from agentarea_llm.domain.models import ModelSpec, ProviderSpec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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
