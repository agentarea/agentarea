"""Seam for container-level egress enforcement on MCP instances.

Core owns the schema (``PolicyEffect.EGRESS`` rows) and the no-op default; the
enterprise edition supplies the real enforcer (default-deny + FQDN allowlist via
NetworkPolicy / Cilium / egress proxy) as a DI swap.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class EgressEnforcer(Protocol):
    """Applies an egress allowlist to an MCP instance's network boundary."""

    async def apply(self, *, mcp_instance_id: str, allowed_hosts: Sequence[str]) -> None:
        """Constrain where an MCP instance may connect.

        ``allowed_hosts`` is the resolved set of host/FQDN patterns; empty means
        default-deny. Must be idempotent (called on instance create/update).
        """
        ...


class NoopEgressEnforcer:
    """Core default: enforces nothing (container enforcement is enterprise-only)."""

    async def apply(self, *, mcp_instance_id: str, allowed_hosts: Sequence[str]) -> None:
        logger.debug(
            "egress allowlist for MCP %s not enforced (needs enterprise edition): %s",
            mcp_instance_id,
            list(allowed_hosts),
        )
