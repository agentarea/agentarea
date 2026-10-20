"""The policy decision on installing a catalog item (ADR-0044)."""

from agentarea_common.auth.context import UserContext
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.rules import (
    CatalogInstallDecision,
    PolicyRule,
    PolicySubjectType,
    decide_catalog_install,
)
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


async def run_time_install_rules(
    session: AsyncSession, user_context: UserContext
) -> list[PolicyRule]:
    """The install rules a run is held to: the workspace's alone.

    A run uses the skills of its agent, whoever started it (a person, a
    trigger's owner, an API key, a delegating agent), so a member's own rules
    apply when they install, never to the runs of an agent they share.
    """
    return await PolicyRuleRepository(session, user_context).list_rules(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id=user_context.workspace_id,
        enabled=True,
    )


class CatalogInstallGuard:
    """The one enforcement point for turning a catalog item into a workspace's own.

    Every path that does so (install, attaching a catalog skill to an agent,
    editing a catalog item, which forks it, importing a skill straight from a
    GitHub URL) asks here before anything is written.
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

    async def run_time_rules(self) -> list[PolicyRule]:
        """The rules a run's skills are decided by (see :func:`run_time_install_rules`)."""
        return await run_time_install_rules(self._session, self._user_context)
