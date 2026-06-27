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
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def _is_existing_tuple_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "already exists" in message or "tuple to be written already existed" in message


async def grant_user_relation(
    *,
    namespace: str,
    object_id: UUID | str,
    relation: str,
    user_id: str,
) -> None:
    """Grant an initial direct relation to the creator when graph auth is enabled.

    Resource create endpoints are still workspace-scoped by the database layer,
    but update/delete endpoints also consult access-control. Without this bootstrap relationship,
    a user can create a resource and then immediately get 403 on their own row.
    """
    settings = get_settings()
    if settings.access_control.ACCESS_CONTROL_BACKEND == "openfga":
        client_type = OpenFGAClient
        backend = "OpenFGA"
    elif settings.access_control.ACCESS_CONTROL_BACKEND == "keto":
        client_type = KetoClient
        backend = "Keto"
    else:
        return

    try:
        client = get_container().get(client_type)
    except ValueError:
        logger.exception("%s is enabled but client is not registered", backend)
        raise HTTPException(
            status_code=503,
            detail=f"{backend} grant writer is unavailable",
        ) from None

    relationship = RelationTuple(
        namespace=namespace,
        object=str(object_id),
        relation=relation,
        subject_id=f"User:{user_id}",
    )
    try:
        await client.write_tuple(relationship)
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        if _is_existing_tuple_error(exc):
            logger.debug("Creator relation already exists in %s: %s", backend, relationship)
            return
        logger.exception("Failed to grant creator relation in %s: %s", backend, relationship)
        raise HTTPException(
            status_code=503,
            detail=f"{backend} grant write failed",
        ) from exc
