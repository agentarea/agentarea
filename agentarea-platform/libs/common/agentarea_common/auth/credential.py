"""What a caller authenticated with, as opposed to who they are.

Authentication settles both once, at the edge. Authorization decides on the
principal: an API key acts as the user who issued it, with that user's roles.
The credential is read only by what records or meters a request (audit, rate
limits) and by the scopes it grants, which a route asks for by name.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Scope(StrEnum):
    """What a credential may do beyond its principal's roles."""

    # Mint or revoke API keys, link a messenger account: anything that lets the
    # caller sign in again. A credential that could do it would outlive its own
    # revocation through the credentials it made.
    CREDENTIALS = "credentials"
    # Create or join a workspace: reach past the one a key was issued for.
    WORKSPACES = "workspaces"


CredentialKind = Literal["session", "oauth", "api_key"]
Surface = Literal["api", "mcp"]


@dataclass(frozen=True)
class Credential:
    """How a request authenticated, and on which surface."""

    kind: CredentialKind
    # The API key's id when ``kind`` is ``api_key``.
    key_id: str | None = None
    surface: Surface = "api"

    @property
    def scopes(self) -> frozenset[Scope]:
        if self.kind == "api_key":
            return frozenset()
        return frozenset(Scope)


# A user signed in through the identity provider.
SESSION = Credential(kind="session")


class ScopeRequiredError(PermissionError):
    """The credential lacks a scope the action needs, whatever the principal's roles."""
