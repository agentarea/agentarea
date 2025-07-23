"""AgentArea LLM Library."""

from .application.provider_service import ProviderService
from .application.embedding_service import EmbeddingService
from .domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec

__version__ = "0.1.0"

__all__ = [
    "ProviderService",
    "EmbeddingService", 
    "ModelInstance",
    "ModelSpec", 
    "ProviderConfig",
    "ProviderSpec",
]
