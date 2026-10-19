"""The policy check every catalog install route makes (ADR-0044).

The single place the install routes ask the policy engine whether the
workspace may install from an item's registry. An id that is no catalog item
the caller can see (a tenant row, another workspace's item) has nothing to
decide here; the install itself then finds or refuses it.
"""

from typing import Annotated
from uuid import UUID

from agentarea_api.api.deps.services import DatabaseSessionDep
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_governance.application.catalog_install import authorize_catalog_install
from agentarea_registry.infrastructure.repository import RegistryItemRepository
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class CatalogInstallPolicy:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self._session = session
        self._user_context = user_context

    async def require_allowed(self, item_id: UUID) -> None:
        """Raise 403 when a policy rule refuses installing from the item's registry."""
        item = await RegistryItemRepository(self._session, self._user_context).get_visible(item_id)
        if item is None:
            return
        decision = await authorize_catalog_install(
            self._session,
            self._user_context,
            registry_id=str(item.registry_id),
            trust=item.registry_trust,
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=403, detail=f"Install refused by policy: {decision.reason}"
            )


async def get_catalog_install_policy(
    session: DatabaseSessionDep, user_context: UserContextDep
) -> CatalogInstallPolicy:
    return CatalogInstallPolicy(session, user_context)


CatalogInstallPolicyDep = Annotated[CatalogInstallPolicy, Depends(get_catalog_install_policy)]
