"""Narrow read-only secret protocol used by outbound channel adapters.

Adapters only ever READ a credential to deliver a message — they never
need to set or rotate one. Pinning the contract to `get_secret` only
keeps two anti-patterns out of the codebase:

  1. Optional secret managers (`BaseSecretManager | None`). The project
     directive bans treating security deps as optional with use-site
     `if not x: return None` fallbacks; missing the dep at boot is a
     boot-time crash, not a delivery-time silent drop.

  2. Read-only adapters being handed a full read/write secret manager
     and raising NotImplementedError on the methods they shouldn't have
     been able to call in the first place (the prior
     `LazySecretManager.set_secret` pattern).
"""

from __future__ import annotations

from typing import Protocol


class SecretReader(Protocol):
    """Adapter-facing view of a secret store. Read-only by design."""

    async def get_secret(self, name: str) -> str | None:
        raise NotImplementedError
