"""Agent package import for AgentArea.

A canonical, declarative package format that bundles agents, skills, MCP
servers and cron automations. Packages are *analyzed* into an
``ImportPreview`` (what will be created, what the user must provide, what is
unsupported) and then *installed* by composing the existing domain services.
"""

from agentarea_bundles.schemas.bundle import (
    SCHEMA_VERSION,
    Bundle,
    BundleAgent,
    BundleAutomation,
    BundleMcp,
    BundleSkill,
    SetupField,
    SetupFieldType,
)
from agentarea_bundles.schemas.preview import (
    EntityKind,
    EntityStatus,
    ImportPreview,
    IssueSeverity,
    PreviewEntity,
    PreviewIssue,
)

__all__ = [
    "SCHEMA_VERSION",
    "Bundle",
    "BundleAgent",
    "BundleAutomation",
    "BundleMcp",
    "BundleSkill",
    "EntityKind",
    "EntityStatus",
    "ImportPreview",
    "IssueSeverity",
    "PreviewEntity",
    "PreviewIssue",
    "SetupField",
    "SetupFieldType",
]
