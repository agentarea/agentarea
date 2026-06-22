"""Unified agent-delegation tool.

Delegation is ONE concept, exposed to the model as a single `delegate_to_<agent>`
tool. The transport ("binding") is chosen per target agent by AgentToolFactory:

- ``local`` binding (AgentDelegationTool): same-platform agent → direct task-service
  call, no HTTP/auth overhead.
- ``a2a`` binding (A2AAgentTool): remote agent → HTTP via the A2A protocol.

Both bindings share the delegation contract (submit → poll until terminal → extract
result). The model sees an identical tool regardless of where the target agent runs;
"local vs remote" is an execution detail behind this facade — never a second tool.
"""

from __future__ import annotations

from typing import Any

from .base_tool import BaseTool


class DelegationTool(BaseTool):
    """Single delegation tool that forwards to a transport binding.

    ``binding_kind`` is ``"local"`` or ``"a2a"`` (observability only — the model
    neither sees nor needs it).
    """

    def __init__(self, binding: BaseTool, binding_kind: str):
        self._binding = binding
        self._binding_kind = binding_kind

    @property
    def binding(self) -> BaseTool:
        return self._binding

    @property
    def binding_kind(self) -> str:
        return self._binding_kind

    @property
    def name(self) -> str:
        return self._binding.name

    @property
    def description(self) -> str:
        return self._binding.description

    def get_schema(self) -> dict[str, Any]:
        return self._binding.get_schema()

    async def execute(self, **kwargs) -> dict[str, Any]:
        return await self._binding.execute(**kwargs)
