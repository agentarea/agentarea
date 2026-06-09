"""Small helpers for keeping resource CRUD aligned with Keto permissions."""

from __future__ import annotations

import logging
from uuid import UUID

from agentarea_common.config import get_settings
from agentarea_common.di.container import get_container
from agentarea_common.rebac import KetoClient, KetoError, KetoUnavailableError, RelationTuple

logger = logging.getLogger(__name__)


async def grant_user_relation(
    *,
    namespace: str,
    object_id: UUID | str,
    relation: str,
    user_id: str,
) -> None:
    """Grant an initial direct relation to the creator when Keto is enabled.

    Resource create endpoints are still workspace-scoped by the database layer,
    but update/delete endpoints also consult Keto. Without this bootstrap tuple,
    a user can create a resource and then immediately get 403 on their own row.
    """
    if not get_settings().keto.KETO_ENABLED:
        return

    try:
        keto = get_container().get(KetoClient)
    except ValueError:
        logger.warning("Keto is enabled but KetoClient is not registered; skipping grant")
        return

    tuple_ = RelationTuple(
        namespace=namespace,
        object=str(object_id),
        relation=relation,
        subject_id=f"User:{user_id}",
    )
    try:
        await keto.write_tuple(tuple_)
    except (KetoError, KetoUnavailableError):
        logger.exception("Failed to grant creator relation in Keto: %s", tuple_)
