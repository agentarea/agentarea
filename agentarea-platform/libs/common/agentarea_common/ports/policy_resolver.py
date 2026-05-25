"""Port that decouples task creation from the concrete governance library.

`tasks` lib depends on this protocol, not on the governance infrastructure
directly. The implementation lives in `agentarea_governance`. Swapping the
governance backend (e.g. to OPA/Cedar/Rego or to an out-of-process service)
becomes a DI change rather than a tasks-lib edit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from agentarea_governance.domain.policies import EffectivePolicy, PolicyDocument


@runtime_checkable
class PolicyResolverPort(Protocol):
    """Resolve and persist governance policy for a single task."""

    async def resolve(
        self,
        *,
        workspace_id: str,
        agent_id: UUID | None = None,
        task_id: UUID | None = None,
        task_policy: PolicyDocument | None = None,
    ) -> EffectivePolicy:
        """Resolve the effective policy for a task.

        Implementations must apply lower-scope-only-tightens validation and
        return an immutable EffectivePolicy snapshot.
        """
        ...

    async def snapshot(
        self,
        *,
        task_id: UUID,
        effective_policy: EffectivePolicy,
    ) -> None:
        """Persist the immutable policy snapshot before workflow dispatch."""
        ...
