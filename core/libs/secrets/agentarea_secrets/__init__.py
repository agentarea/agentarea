"""AgentArea Secrets Library.

Provides multiple secret manager implementations:
- DatabaseSecretManager: Encrypted PostgreSQL storage (default)
- InfisicalSecretManager: External Infisical service integration
"""

__version__ = "0.1.0"

from .database_secret_manager import DatabaseSecretManager
from .infisical_secret_manager import InfisicalSecretManager
from .secret_manager_factory import (
    SecretManagerFactory,
    get_real_secret_manager,
    get_secret_manager,
)

__all__ = [
    "DatabaseSecretManager",
    "InfisicalSecretManager",
    "SecretManagerFactory",
    "get_real_secret_manager",
    "get_secret_manager",
]
