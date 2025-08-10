"""AgentArea LLM Library."""

from .application.embedding_service import EmbeddingService
from .application.provider_service import ProviderService
from .domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec

__version__ = "0.1.0"

__all__ = [
    "EmbeddingService",
    "ModelInstance",
    "ModelSpec",
    "ProviderConfig",
    "ProviderService",
    "ProviderSpec",
]
