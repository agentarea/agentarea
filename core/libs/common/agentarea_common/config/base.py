"""Base configuration classes."""

from pydantic_settings import BaseSettings


class BaseAppSettings(BaseSettings):
    """Base settings class with common configuration."""

    model_config = {"env_file": ".env", "extra": "ignore"}
