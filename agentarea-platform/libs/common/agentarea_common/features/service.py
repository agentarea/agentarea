"""Feature service for deployment-mode-specific behaviors.

Note: This controls UI/presentation concerns only.
Implementation swapping (e.g., which PermissionService) is handled
by the plugin extension registry, not feature flags.
"""

from enum import StrEnum


class DeploymentMode(StrEnum):
    OSS = "oss"
    ENTERPRISE = "enterprise"


class FeatureService:
    """Controls deployment-mode-specific behaviors."""

    def __init__(self, mode: DeploymentMode = DeploymentMode.OSS):
        self.mode = mode

    @property
    def show_system_entity_badge(self) -> bool:
        """UI: show 'System' badge on system entities."""
        return self.mode == DeploymentMode.ENTERPRISE

    @property
    def system_entities_read_only_in_ui(self) -> bool:
        """UI: disable edit controls for system entities."""
        return self.mode == DeploymentMode.ENTERPRISE

    @property
    def enable_usage_metering(self) -> bool:
        """Enable usage metering and billing integration."""
        return self.mode == DeploymentMode.ENTERPRISE

    @property
    def show_governance_overlay(self) -> bool:
        """Network view: show governance interceptor overlay."""
        return self.mode == DeploymentMode.ENTERPRISE

    @property
    def enable_network_rebac(self) -> bool:
        """Network view: filter nodes via Keto ReBAC."""
        return self.mode == DeploymentMode.ENTERPRISE
