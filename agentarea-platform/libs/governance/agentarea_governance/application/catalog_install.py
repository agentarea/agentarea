"""The policy decision on installing a catalog item (ADR-0044)."""

from agentarea_common.auth.context import UserContext
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.rules import CatalogInstallDecision, PolicySubjectType, decide_catalog_install
from ..infrastructure.repository import PolicyRuleRepository


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
