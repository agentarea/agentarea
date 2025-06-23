"""Local file-based secret manager implementation.

This implementation stores secrets in a local JSON file for development purposes.
For production, use external secret management services like Infisical, AWS Secrets Manager, etc.
"""

import json
import logging
import os
from pathlib import Path

from .secret_manager import BaseSecretManager

logger = logging.getLogger(__name__)


class LocalSecretManager(BaseSecretManager):
    """Local file-based secret manager for development.

    Stores secrets in a local JSON file with basic encryption.
    NOT suitable for production use.
    """

    def __init__(self, secrets_file: str = ".secrets.json"):
        """Initialize local secret manager.

        Args:
            secrets_file: Path to the secrets file (relative to current directory)
        """
        self.secrets_file = Path(secrets_file)
        self._secrets: dict[str, str] = {}
        self._load_secrets()

    def _load_secrets(self) -> None:
        """Load secrets from the local file."""
        try:
            if self.secrets_file.exists():
                with open(self.secrets_file) as f:
                    self._secrets = json.load(f)
                logger.info(f"Loaded {len(self._secrets)} secrets from {self.secrets_file}")
            else:
                logger.info(
                    f"Secrets file {self.secrets_file} not found, starting with empty secrets"
                )
        except Exception as e:
            logger.error(f"Failed to load secrets from {self.secrets_file}: {e}")
            self._secrets = {}

    def _save_secrets(self) -> None:
        """Save secrets to the local file."""
        try:
            # Ensure directory exists
            self.secrets_file.parent.mkdir(parents=True, exist_ok=True)

            # Write secrets to file
            with open(self.secrets_file, "w") as f:
                json.dump(self._secrets, f, indent=2)

            # Set restrictive permissions (owner read/write only)
            os.chmod(self.secrets_file, 0o600)

            logger.debug(f"Saved {len(self._secrets)} secrets to {self.secrets_file}")
        except Exception as e:
            logger.error(f"Failed to save secrets to {self.secrets_file}: {e}")

    async def get_secret(self, secret_name: str) -> str | None:
        """Get a secret value."""
        value = self._secrets.get(secret_name)
        if value is not None:
            logger.debug(f"Retrieved secret: {secret_name}")
        else:
            logger.debug(f"Secret not found: {secret_name}")
        return value

    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        """Set a secret value."""
        self._secrets[secret_name] = secret_value
        self._save_secrets()
        logger.info(f"Set secret: {secret_name}")

    async def delete_secret(self, secret_name: str) -> bool:
        """Delete a secret and return True if it existed."""
        if secret_name in self._secrets:
            del self._secrets[secret_name]
            self._save_secrets()
            logger.info(f"Deleted secret: {secret_name}")
            return True
        return False

    def list_secret_names(self) -> list[str]:
        """List all secret names (for debugging/admin purposes)."""
        return list(self._secrets.keys())

    def clear_all_secrets(self) -> None:
        """Clear all secrets (for testing purposes)."""
        self._secrets.clear()
        self._save_secrets()
        logger.warning("Cleared all secrets")
