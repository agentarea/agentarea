"""A workspace's own OAuth app, shared by every Connect flow.

Two flows let a workspace supply its own OAuth client: remote MCP instances
(``mcp_oauth_connect``) and one-click API connections (``connection_oauth``).
Both accept the credentials either typed in or referenced from workspace
secrets, and both must hold the same line — exactly one source per credential,
user-owned secrets the caller created or administers only (the client ID comes
back inside the authorize URL), and the secret value persisted on an auth config
rather than copied into expiring OAuth state. Those rules live here so the two
flows cannot drift into two different security postures.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_secrets.catalog_service import (
    ManagedSecretError,
    SecretAccessDeniedError,
    SecretCatalogService,
    SecretNotFoundError,
)
from agentarea_secrets.models import EncryptedSecret
from fastapi import HTTPException
from pydantic import BaseModel, Field


class CustomOAuthAppFields(BaseModel):
    """The OAuth client a workspace brings for providers that have no DCR."""

    client_id: str | None = Field(default=None, min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    client_id_secret_id: UUID | None = Field(
        default=None,
        description="Existing user-owned workspace secret containing the OAuth client ID.",
    )
    client_secret_secret_id: UUID | None = Field(
        default=None,
        description="Existing user-owned workspace secret containing the OAuth client secret.",
    )

    def has_any_custom_credential(self) -> bool:
        return any(
            value is not None
            for value in (
                self.client_id,
                self.client_secret,
                self.client_id_secret_id,
                self.client_secret_secret_id,
            )
        )

    def validate_custom_credential_sources(self) -> None:
        """Require exactly one source per credential.

        Raises:
            ValueError: when a credential is supplied twice or not at all.
        """
        for label, value, secret_id in (
            ("client ID", self.client_id, self.client_id_secret_id),
            ("client secret", self.client_secret, self.client_secret_secret_id),
        ):
            if (value is None) == (secret_id is None):
                raise ValueError(
                    f"Custom OAuth {label} must be entered or selected from workspace secrets."
                )


@dataclass
class ResolvedOAuthApp:
    """Credentials split the way an ``MCPAuthConfig`` stores them."""

    client_id: str
    config: dict[str, Any] = field(default_factory=dict)
    credentials: dict[str, Any] = field(default_factory=dict)
    # (secret id, auth-config field) pairs to register once the config exists.
    references: list[tuple[UUID, str]] = field(default_factory=list)


async def workspace_secret_value(
    catalog: SecretCatalogService,
    manager: BaseSecretManager,
    secret_id: UUID,
    label: str,
) -> tuple[EncryptedSecret, str]:
    """Resolve a secret the caller may use, without exposing its value."""
    try:
        secret = await catalog.get_for_use(secret_id)
    except SecretNotFoundError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Selected OAuth {label} secret is not available in this workspace.",
        ) from exc
    except ManagedSecretError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Selected OAuth {label} must be a user-owned workspace secret.",
        ) from exc
    except SecretAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    value = await manager.get_secret(secret.secret_name)
    if not value:
        raise HTTPException(
            status_code=422,
            detail=f"Selected OAuth {label} secret has no value.",
        )
    return secret, value


async def resolve_custom_oauth_app(
    fields: CustomOAuthAppFields,
    *,
    catalog: SecretCatalogService,
    manager: BaseSecretManager,
) -> ResolvedOAuthApp:
    """Turn a request's credential fields into auth-config storage.

    A referenced secret is stored by name so rotating it does not need the
    connection to be re-authorized; a typed-in secret is stored encrypted under
    the auth config itself.
    """
    resolved = ResolvedOAuthApp(client_id="")

    if fields.client_id_secret_id is not None:
        secret, client_id = await workspace_secret_value(
            catalog, manager, fields.client_id_secret_id, "client ID"
        )
        resolved.client_id = client_id
        resolved.config["client_id_secret_name"] = secret.secret_name
        resolved.references.append((secret.id, "client_id"))
    else:
        resolved.client_id = str(fields.client_id)
        resolved.config["client_id"] = resolved.client_id

    if fields.client_secret_secret_id is not None:
        secret, _ = await workspace_secret_value(
            catalog, manager, fields.client_secret_secret_id, "client secret"
        )
        resolved.config["client_secret_secret_name"] = secret.secret_name
        resolved.references.append((secret.id, "client_secret"))
    else:
        resolved.credentials["client_secret"] = fields.client_secret

    return resolved
