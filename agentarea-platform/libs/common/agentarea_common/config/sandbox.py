"""Sandbox configuration shared by the API and the worker."""

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings
from .mcp import PUBLISHED_SECRET_VALUES


class SandboxSettings(BaseAppSettings):
    """Bearer secrets the platform presents to the sandbox runtime."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_SANDBOX_")

    INSPECT_SECRET: SecretStr | None = None
    FILE_SECRET: SecretStr | None = None
    CONTROL_SECRET: SecretStr | None = None

    @field_validator("FILE_SECRET", "CONTROL_SECRET")
    @classmethod
    def _reject_published_secret(
        cls, value: SecretStr | None, info: ValidationInfo
    ) -> SecretStr | None:
        if value is not None and value.get_secret_value() in PUBLISHED_SECRET_VALUES:
            raise ValueError(
                f"{info.field_name} is set to a value published in the AgentArea repository; "
                "generate a new one (scripts/gen-dev-secrets.sh rotates it) and restart"
            )
        return value
