"""Workflow configuration."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkflowSettings(BaseSettings):
    """Workflow execution configuration.

    ENGINE determines which settings are required:
    - "temporal": all Temporal settings must be provided (no defaults)
    - "direct": Temporal settings are ignored
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_WF_")

    ENGINE: str = "temporal"

    # Required when ENGINE=temporal, ignored otherwise
    TEMPORAL_URL: str = ""
    NAMESPACE: str = ""
    QUEUE: str = ""

    # Worker settings
    MAX_ACTIVITIES: int = 10
    MAX_WORKFLOWS: int = 5

    @model_validator(mode="after")
    def validate_engine_settings(self):
        """Validate that required settings are present for the chosen engine."""
        if self.ENGINE == "temporal":
            missing = []
            if not self.TEMPORAL_URL:
                missing.append("AGENTAREA_WF_TEMPORAL_URL")
            if not self.NAMESPACE:
                missing.append("AGENTAREA_WF_NAMESPACE")
            if not self.QUEUE:
                missing.append("AGENTAREA_WF_QUEUE")
            if missing:
                raise ValueError(f"AGENTAREA_WF_ENGINE=temporal requires: {', '.join(missing)}")
        elif self.ENGINE not in ("temporal", "direct"):
            raise ValueError(
                f"Unknown AGENTAREA_WF_ENGINE '{self.ENGINE}'. Must be 'temporal' or 'direct'."
            )
        return self
