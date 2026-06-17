"""Small helpers for keeping resource CRUD aligned with graph permissions."""

from __future__ import annotations

import logging
from uuid import UUID

from agentarea_common.config import get_settings
from agentarea_common.di.container import get_container
from agentarea_common.rebac import (
    KetoClient,
    KetoError,
    KetoUnavailableError,
    OpenFGAClient,
    OpenFGAError,
    OpenFGAUnavailableError,
    RelationTuple,
)

logger = logging.getLogger(__name__)


async def grant_user_relation(
    *,
    namespace: str,
    object_id: UUID | str,
    relation: str,
    user_id: str,
) -> None:
    """Grant an initial direct relation to the creator when graph auth is enabled.

    Resource create endpoints are still workspace-scoped by the database layer,
    but update/delete endpoints also consult ReBAC. Without this bootstrap tuple,
    a user can create a resource and then immediately get 403 on their own row.
    """
    settings = get_settings()
    if settings.openfga.OPENFGA_ENABLED:
        client_type = OpenFGAClient
        backend = "OpenFGA"
    elif settings.keto.KETO_ENABLED:
        client_type = KetoClient
        backend = "Keto"
    else:
        return

    try:
        client = get_container().get(client_type)
    except ValueError:
        logger.warning("%s is enabled but client is not registered; skipping grant", backend)
        return

    tuple_ = RelationTuple(
        namespace=namespace,
        object=str(object_id),
        relation=relation,
        subject_id=f"User:{user_id}",
    )
    try:
        await client.write_tuple(tuple_)
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError):
        logger.exception("Failed to grant creator relation in %s: %s", backend, tuple_)
