"""Local file-based secret manager implementation.

This implementation stores secrets in a local JSON file for development purposes.
For production, use external secret management services like Infisical, AWS Secrets Manager, etc.
"""

import json
import logging
import os
from pathlib import Path

from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class LocalSecretManager(BaseSecretManager):
    """Local file-based secret manager for development.

    Stores secrets in a local JSON file with symmetric encryption.
    NOT suitable for production use.
    """

    def __init__(self, secrets_file: str = ".secrets.json", key_file: str = ".secrets.key"):
        """Initialize local secret manager.

        Args:
            secrets_file: Path to the secrets file (relative to current directory)
            key_file: Path to the encryption key file (relative to current directory)
        """
        self.secrets_file = Path(secrets_file)
        self.key_file = Path(key_file)
        self._secrets: dict[str, str] = {}
        self._fernet = self._load_or_create_key()
        self._load_secrets()

    def _load_or_create_key(self) -> Fernet:
        """Load or create a symmetric encryption key."""
        if self.key_file.exists():
            with open(self.key_file, "rb") as f:
                key = f.read()
            logger.info(f"Loaded encryption key from {self.key_file}")
        else:
            key = Fernet.generate_key()
            self.key_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.key_file, "wb") as f:
                f.write(key)
            os.chmod(self.key_file, 0o600)
            logger.info(f"Generated new encryption key at {self.key_file}")
        return Fernet(key)

    def _encrypt(self, value: str) -> str:
        """Encrypt a secret value."""
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def _decrypt(self, value: str) -> str:
        """Decrypt a secret value."""
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except (InvalidToken, Exception):
            logger.error("Failed to decrypt secret value")
            return ""

    def _load_secrets(self) -> None:
        """Load secrets from the local file."""
        try:
            if self.secrets_file.exists():
                with open(self.secrets_file) as f:
                    raw_secrets = json.load(f)
                self._secrets = raw_secrets
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
        encrypted_value = self._secrets.get(secret_name)
        if encrypted_value is not None:
            value = self._decrypt(encrypted_value)
            logger.debug(f"Retrieved secret: {secret_name}")
            return value
        else:
            logger.debug(f"Secret not found: {secret_name}")
            return None

    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        """Set a secret value."""
        encrypted_value = self._encrypt(secret_value)
        self._secrets[secret_name] = encrypted_value
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
