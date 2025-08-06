"""AgentArea Secrets Library."""

__version__ = "0.1.0"

from .infisical_factory import get_real_secret_manager
from .infisical_secret_manager import InfisicalSecretManager
from .local_secret_manager import LocalSecretManager

__all__ = [
    "InfisicalSecretManager",
    "LocalSecretManager",
    "get_real_secret_manager",
]
