"""Configuration management for AgentArea CLI."""

import json
import os
from pathlib import Path
from typing import Any


class Config:
    """Centralized configuration management."""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or Path.home() / ".agentarea"
        self.config_file = self.config_dir / "config.json"
        self.config_dir.mkdir(exist_ok=True)
        self._config_cache: dict[str, Any] | None = None

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from file with caching."""
        if self._config_cache is not None:
            return self._config_cache

        if not self.config_file.exists():
            self._config_cache = {}
            return self._config_cache

        try:
            with open(self.config_file) as f:
                self._config_cache = json.load(f)
                return self._config_cache
        except (OSError, json.JSONDecodeError):
            self._config_cache = {}
            return self._config_cache

    def _save_config(self, config: dict[str, Any]) -> None:
        """Save configuration to file and update cache."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            self._config_cache = config
        except OSError as e:
            raise RuntimeError(f"Failed to save configuration: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        config = self._load_config()
        keys = key.split('.')
        value = config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value."""
        config = self._load_config()
        keys = key.split('.')
        current = config

        # Navigate to the parent of the target key
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        # Set the final value
        current[keys[-1]] = value
        self._save_config(config)

    def delete(self, key: str) -> None:
        """Delete configuration value."""
        config = self._load_config()
        keys = key.split('.')
        current = config

        # Navigate to the parent of the target key
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                return  # Key doesn't exist
            current = current[k]

        # Delete the final key if it exists
        if keys[-1] in current:
            del current[keys[-1]]
            self._save_config(config)

    def clear_cache(self) -> None:
        """Clear the configuration cache."""
        self._config_cache = None


class AuthConfig:
    """Authentication-specific configuration management."""

    def __init__(self, config: Config):
        self.config = config

    def get_token(self) -> str | None:
        """Get stored authentication token."""
        return self.config.get("auth.token")

    def set_token(self, token: str) -> None:
        """Store authentication token."""
        self.config.set("auth.token", token)

    def get_api_url(self) -> str:
        """Get stored API URL."""
        return self.config.get("api_url", "http://localhost:8000")

    def set_api_url(self, url: str) -> None:
        """Store API URL."""
        self.config.set("api_url", url.rstrip("/"))

    def clear_auth(self) -> None:
        """Clear authentication data."""
        self.config.delete("auth")

    def is_authenticated(self) -> bool:
        """Check if user is authenticated."""
        return self.get_token() is not None


# Environment variable overrides
def get_env_config() -> dict[str, str]:
    """Get configuration from environment variables."""
    env_config = {}

    # API URL from environment
    if api_url := os.getenv("AGENTAREA_API_URL"):
        env_config["api_url"] = api_url

    # Debug mode
    if debug := os.getenv("AGENTAREA_DEBUG"):
        env_config["debug"] = debug.lower() in ("true", "1", "yes")

    return env_config
