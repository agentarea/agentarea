"""What a workspace's runtime used: compute it reserved and storage it keeps.

Additive extension point (see AGENTS.md → EXTENSION POINTS): an installed
``workspace_usage`` extension is active by being installed. Without one there is
nothing metered beyond the spend ledger — a self-hosted install meters no runtime.

Quantities only, never a price: what a unit costs is billing's answer.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from .registry import ExtensionRegistry

WORKSPACE_USAGE_EXTENSION = "workspace_usage"


@dataclass(frozen=True)
class WorkspaceUsage:
    """A workspace's runtime usage since a UTC instant.

    ``storage_gib`` is what the workspace stores now, not an integral over time.
    """

    cpu_core_hours: Decimal
    memory_gib_hours: Decimal
    storage_gib: Decimal


@runtime_checkable
class WorkspaceUsageSource(Protocol):
    async def usage_since(self, workspace_id: str, since: datetime) -> WorkspaceUsage:
        """Usage of ``workspace_id`` since ``since`` (UTC)."""
        ...


class WorkspaceUsageUnavailableError(RuntimeError):
    """An installed workspace_usage extension could not be resolved."""


def get_workspace_usage_source() -> WorkspaceUsageSource | None:
    """The installed source, or None when this deployment meters no runtime."""
    factory = ExtensionRegistry.get_factory(WORKSPACE_USAGE_EXTENSION)
    if factory is None:
        failure = ExtensionRegistry.get_failure(WORKSPACE_USAGE_EXTENSION)
        if failure is not None:
            raise WorkspaceUsageUnavailableError(
                f"workspace_usage extension is installed but failed to load: {failure}"
            )
        return None
    source = factory()
    if not isinstance(source, WorkspaceUsageSource):
        kind = type(source).__name__
        raise WorkspaceUsageUnavailableError(
            f"workspace_usage extension returned {kind}, not a WorkspaceUsageSource"
        )
    return source
