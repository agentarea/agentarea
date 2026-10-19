"""The policy decision on installing a catalog item (ADR-0044)."""

from agentarea_common.auth.context import UserContext
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.rules import CatalogInstallDecision, PolicySubjectType, decide_catalog_install
from ..infrastructure.repository import PolicyRuleRepository


class CatalogInstallRefusedError(PermissionError):
    """A policy rule refuses installing from the item's registry."""


async def authorize_catalog_install(
    session: AsyncSession, user_context: UserContext, *, registry_id: str, trust: str
) -> CatalogInstallDecision:
    """Decide from the workspace's rules and the installing user's."""
    repo = PolicyRuleRepository(session, user_context)
    rules = [
        *await repo.list_rules(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id=user_context.workspace_id,
            enabled=True,
        ),
        *await repo.list_rules(
            subject_type=PolicySubjectType.USER,
            subject_id=user_context.user_id,
            enabled=True,
        ),
    ]
    return decide_catalog_install(rules, registry_id=registry_id, trust=trust)


class CatalogInstallGuard:
    """The one enforcement point for turning a catalog item into a workspace's own.

    Every path that does so (install, attaching a catalog skill to an agent,
    editing a catalog item, which forks it) asks here before anything is written.
    """

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self._session = session
        self._user_context = user_context

    async def require_allowed(self, *, registry_id: str | None, trust: str | None) -> None:
        if registry_id is None or trust is None:
            raise ValueError("A catalog item without its registry cannot be checked for install")
        decision = await authorize_catalog_install(
            self._session, self._user_context, registry_id=registry_id, trust=trust
        )
        if not decision.allowed:
            raise CatalogInstallRefusedError(f"Install refused by policy: {decision.reason}")
