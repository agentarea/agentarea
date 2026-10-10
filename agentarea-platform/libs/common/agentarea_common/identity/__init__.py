"""External accounts recognised as platform users.

A link records how a person is recognised in a messenger: ``telegram`` account
``12345`` is user ``u``. It answers "who is this?" and nothing else; whether
that person may run an agent is the graph's ``can_invoke``.
"""

from .linking import LINK_TTL_SECONDS, LinkCodes
from .models import UserExternalIdentity
from .repository import ExternalIdentityRepository, ExternalIdentityTakenError

__all__ = [
    "LINK_TTL_SECONDS",
    "ExternalIdentityRepository",
    "ExternalIdentityTakenError",
    "LinkCodes",
    "UserExternalIdentity",
]
