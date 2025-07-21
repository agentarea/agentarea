import os
from datetime import datetime
from uuid import UUID, uuid4

import yaml
from agentarea_common.base.repository import BaseRepository

from agentarea_llm.domain.models import LLMModel


class YAMLLLMModelRepository(BaseRepository[LLMModel]):
    """A repository implementation that reads LLM models from a YAML file.

    This is a temporary solution until the database implementation is ready.
    """

    def __init__(self, yaml_path: str | None = None):
        """Initialize the repository with the path to the YAML file.

        Args:
            yaml_path: Path to the YAML file. If None, uses the default path.
        """
        if yaml_path is None:
            # Default path is relative to the current file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.yaml_path = os.path.join(current_dir, "providers.yaml")
        else:
            self.yaml_path = yaml_path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.yaml_path = os.path.join(current_dir, "providers.yaml")
        self._providers_data = None
        self._load_yaml()

    def _load_yaml(self) -> dict:
        """Load the YAML file and cache the data."""
        if self._providers_data is None:
            with open(self.yaml_path) as f:
                self._providers_data = yaml.safe_load(f)
        return self._providers_data

    async def get(self, id: UUID) -> LLMModel | None:
        """Get a model by ID.

        Note: This implementation doesn't support getting by ID since the YAML
        file doesn't have IDs. It will always return None.
        """
        # This implementation doesn't support getting by ID
        return None

    async def list(
        self,
        model_id: UUID | None = None,
        status: str | None = None,
        is_public: bool | None = None,
        provider: str | None = None,
    ) -> list[LLMModel]:
        """List models from the YAML file.

        Args:
            model_id: Filter by model ID (not implemented)
            status: Filter by status (not implemented)
            is_public: Filter by public status (not implemented)
            provider: Filter by provider name

        Returns:
            List of LLM models
        """
        providers = self._providers_data.get("providers", {})

        models = []

        for provider_id, provider_data in providers.items():
            if provider and provider != provider_id:
                continue

            provider_data.get("name", provider_id)

            for model_data in provider_data.get("models", []):
                # Create a model instance with data from YAML
                model = LLMModel(
                    id=uuid4(),  # Generate a random ID
                    name=model_data.get("name", ""),
                    description=model_data.get("description", ""),
                    provider_id=provider_id,  # Use provider_id instead of provider
                    model_type=model_data.get("name", ""),  # Using name as model_type
                    endpoint_url="",  # Default empty endpoint URL
                    context_window=str(model_data.get("context_window", 0)),
                    status="active",  # Default status
                    is_public=True,  # Default public status
                    updated_at=datetime.now(),
                    created_at=datetime.now(),
                )
                models.append(model)

        return models

    async def create(self, model: LLMModel) -> LLMModel:
        """Create a model.

        Note: This implementation doesn't support creating models.
        """
        # This implementation doesn't support creating models
        raise NotImplementedError("Creating models is not supported in YAML repository")

    async def update(self, model: LLMModel) -> LLMModel:
        """Update a model.

        Note: This implementation doesn't support updating models.
        """
        # This implementation doesn't support updating models
        raise NotImplementedError("Updating models is not supported in YAML repository")

    async def delete(self, id: UUID) -> bool:
        """Delete a model.

        Note: This implementation doesn't support deleting models.
        """
        # This implementation doesn't support deleting models
        raise NotImplementedError("Deleting models is not supported in YAML repository")
