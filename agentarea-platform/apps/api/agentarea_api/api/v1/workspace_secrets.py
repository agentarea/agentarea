"""Workspace secrets.

Values go in and never come back out — no endpoint here returns one, and there
is deliberately no read-the-value route to add one to later. Everything is
scoped to secrets the user owns: the rows the platform mints for a connection
are named after it and resolved by name, so letting this API rewrite or remove
one would break the connection from the outside.
"""

import logging
from uuid import UUID

from agentarea_api.api.deps.services import (
    DatabaseSessionDep,
    SecretCatalogServiceDep,
    UserContextDep,
)
from agentarea_secrets.catalog_service import (
    SURFACED_OWNER_TYPES,
    DuplicateSecretNameError,
    ManagedSecretError,
    SecretInUseError,
    SecretNotFoundError,
)
from agentarea_secrets.models import EncryptedSecret
from agentarea_secrets.naming import SecretNameError, managed_field
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ._secret_owners import resolve_owner_names

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/secrets", tags=["secrets"])


class SecretConsumer(BaseModel):
    consumer_type: str = Field(description="Kind of thing using the secret, e.g. provider_config.")
    consumer_id: str = Field(description="Id of the using entity.")
    field: str = Field(description="Which slot on that entity — a header name, an env var.")


class SecretOwner(BaseModel):
    """The connection a managed secret belongs to."""

    type: str = Field(description="Kind of owner, e.g. mcp_instance or provider_config.")
    id: str = Field(description="Its id, for deep-linking to it.")
    name: str | None = Field(
        default=None,
        description="Its display name, or null when the owner no longer exists.",
    )
    field: str | None = Field(
        default=None,
        description="Which slot on the owner this fills — an env var, a header name.",
    )


class SecretResponse(BaseModel):
    """A secret's metadata. The value is never part of this."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str = Field(description="Unique within the workspace.")
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    used_by: list[SecretConsumer] = Field(default_factory=list)
    owner: SecretOwner | None = Field(
        default=None,
        description=(
            "Set when a connection holds this secret on the user's behalf. Such a "
            "secret is read-only here and is changed through its owner."
        ),
    )

    @classmethod
    def of(
        cls,
        secret: EncryptedSecret,
        used_by: list[SecretConsumer],
        owner_name: str | None = None,
    ) -> "SecretResponse":
        owner = None
        if secret.owner_type is not None and secret.owner_id is not None:
            owner = SecretOwner(
                type=secret.owner_type,
                id=secret.owner_id,
                name=owner_name,
                field=managed_field(secret.secret_name),
            )
        return cls(
            id=secret.id,
            name=secret.secret_name,
            description=secret.description,
            created_at=secret.created_at.isoformat() if secret.created_at else None,
            updated_at=secret.updated_at.isoformat() if secret.updated_at else None,
            used_by=used_by,
            owner=owner,
        )


class SecretCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description=(
            "2-64 characters: lowercase letters, digits, '-' and '_', starting and "
            "ending with a letter or digit. Prefixes the platform uses for its own "
            "secrets are rejected."
        ),
    )
    value: str = Field(min_length=1, description="Stored encrypted; never returned.")
    description: str | None = Field(default=None, max_length=1000)


class SecretValueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, description="Replaces the stored value.")


class SecretDescriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=1000)


def _not_found(exc: SecretNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _managed(exc: ManagedSecretError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get("", response_model=list[SecretResponse])
async def list_secrets(
    catalog: SecretCatalogServiceDep,
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
) -> list[SecretResponse]:
    """Every credential in the workspace the user would recognise as theirs.

    Their own, plus the ones connections hold for them — the latter read-only.
    Values are not included, here or anywhere.
    """
    secrets = await catalog.list_visible_secrets()
    owner_names = await resolve_owner_names(
        db_session,
        user_context.workspace_id,
        [(s.owner_type, s.owner_id) for s in secrets if s.owner_type and s.owner_id],
    )

    out: list[SecretResponse] = []
    for secret in secrets:
        # A managed secret's consumer is its owner, which is already on the row.
        # Only user-owned secrets can be shared, so only they need the lookup.
        consumers = [] if secret.owner_type else await catalog.consumers(secret.id)
        out.append(
            SecretResponse.of(
                secret,
                [SecretConsumer(**c.__dict__) for c in consumers],
                owner_names.get((secret.owner_type or "", secret.owner_id or "")),
            )
        )
    return out


@router.post("", response_model=SecretResponse, status_code=status.HTTP_201_CREATED)
async def create_secret(payload: SecretCreate, catalog: SecretCatalogServiceDep) -> SecretResponse:
    try:
        secret = await catalog.create_user_secret(payload.name, payload.value, payload.description)
    except SecretNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except DuplicateSecretNameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SecretResponse.of(secret, [])


@router.get("/{secret_id}", response_model=SecretResponse)
async def get_secret(
    secret_id: UUID,
    catalog: SecretCatalogServiceDep,
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
) -> SecretResponse:
    """Read one secret's metadata, whether the user owns it or a connection does.

    Managed secrets are readable because the list shows them; hiding them here
    would 404 every row the page invites you to click. They stay unwritable —
    the write routes below still refuse them.
    """
    try:
        secret = await catalog.get(secret_id)
    except SecretNotFoundError as exc:
        raise _not_found(exc) from exc

    if secret.owner_type is not None and secret.owner_type not in SURFACED_OWNER_TYPES:
        # Machine-generated and absent from every list, so it does not exist as
        # far as this API is concerned.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No secret {secret_id} in this workspace",
        )

    consumers = [] if secret.owner_type else await catalog.consumers(secret.id)
    owner_name = None
    if secret.owner_type and secret.owner_id:
        owner_name = (
            await resolve_owner_names(
                db_session, user_context.workspace_id, [(secret.owner_type, secret.owner_id)]
            )
        ).get((secret.owner_type, secret.owner_id))

    return SecretResponse.of(secret, [SecretConsumer(**c.__dict__) for c in consumers], owner_name)


@router.patch("/{secret_id}", response_model=SecretResponse)
async def update_secret_description(
    secret_id: UUID, payload: SecretDescriptionUpdate, catalog: SecretCatalogServiceDep
) -> SecretResponse:
    try:
        secret = await catalog.update_description(secret_id, payload.description)
    except SecretNotFoundError as exc:
        raise _not_found(exc) from exc
    except ManagedSecretError as exc:
        raise _managed(exc) from exc
    consumers = await catalog.consumers(secret.id)
    return SecretResponse.of(secret, [SecretConsumer(**c.__dict__) for c in consumers])


@router.put("/{secret_id}/value", response_model=SecretResponse)
async def rotate_secret(
    secret_id: UUID, payload: SecretValueUpdate, catalog: SecretCatalogServiceDep
) -> SecretResponse:
    """Replace the stored value. Everything pointing at this secret picks up the new one."""
    try:
        secret = await catalog.rotate_user_secret(secret_id, payload.value)
    except SecretNotFoundError as exc:
        raise _not_found(exc) from exc
    except ManagedSecretError as exc:
        raise _managed(exc) from exc
    consumers = await catalog.consumers(secret.id)
    return SecretResponse.of(secret, [SecretConsumer(**c.__dict__) for c in consumers])


@router.delete("/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(secret_id: UUID, catalog: SecretCatalogServiceDep) -> None:
    try:
        await catalog.delete_user_secret(secret_id)
    except SecretNotFoundError as exc:
        raise _not_found(exc) from exc
    except ManagedSecretError as exc:
        raise _managed(exc) from exc
    except SecretInUseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "used_by": [
                    {
                        "consumer_type": c.consumer_type,
                        "consumer_id": c.consumer_id,
                        "field": c.field,
                    }
                    for c in exc.consumers
                ],
            },
        ) from exc
