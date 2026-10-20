"""OAuth Connect — sign in to a remote MCP server or a catalog API, one flow for both.

    GET  /v1/workspaces/{workspace}/oauth/preflight  — can it be authorized, and with what
    POST /v1/workspaces/{workspace}/oauth/authorize  — pick the OAuth client, return the
                                                       provider's sign-in URL
    GET  /v1/oauth/callback                          — the one redirect URI: park the code,
                                                       send the browser to the finish page
    POST /v1/oauth/finish                            — the person who started the flow
                                                       exchanges the code, attaching the
                                                       credential

Preflight exists so the UI never offers a Connect button that cannot complete:
a provider with neither a platform app (AGENTAREA_MCP_OAUTH_APPS) nor Dynamic
Client Registration needs the workspace's own OAuth app, and that has to be
asked for before the redirect, not discovered as an error after it.

Implements the client side of the MCP Authorization spec, RFC 9728, RFC 8414,
RFC 7591 and OAuth 2.1 + PKCE (S256).
"""

from typing import Annotated, Literal
from uuid import UUID

from agentarea_api.api.deps.services import DatabaseSessionDep, SecretCatalogServiceDep
from agentarea_api.api.v1.oauth_app_credentials import CustomOAuthAppFields
from agentarea_api.oauth_connect import service as oauth_connect
from agentarea_api.oauth_connect.pages import callback_uri
from agentarea_api.oauth_connect.targets import (
    CatalogItemTarget,
    ConnectTarget,
    MCPInstanceTarget,
    MCPSpecTarget,
    PreflightTarget,
)
from agentarea_common.auth.dependencies import PrincipalDep, UserContextDep
from agentarea_common.auth.route_authz import enforced_in_handler, unrestricted
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Preflight and authorize act in a workspace; the callback is a redirect from
# the provider and carries no session; the finish names no workspace, the
# flow it redeems does.
router = APIRouter(prefix="/oauth", tags=["oauth-connect"])
public_router = APIRouter(prefix="/oauth", tags=["oauth-connect"])
principal_router = APIRouter(prefix="/oauth", tags=["oauth-connect"])


class OAuthAuthorizeRequest(CustomOAuthAppFields):
    """Start a sign-in for one MCP instance or one catalog API.

    ``auto`` uses the operator's platform app when one serves the provider, else
    registers AgentArea with it (RFC 7591). ``custom`` uses an OAuth app the
    workspace registered with the provider, and overrides either.
    """

    model_config = ConfigDict(extra="forbid")

    instance_id: UUID | None = Field(default=None, description="MCP instance to sign in to.")
    catalog_item_id: UUID | None = Field(
        default=None,
        description="Catalog API to connect; the connection is created by this request.",
    )
    credential_mode: Literal["auto", "custom"] = "auto"
    return_to: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def validate_target_and_credentials(self) -> OAuthAuthorizeRequest:
        if (self.instance_id is None) == (self.catalog_item_id is None):
            raise ValueError("Pass exactly one of instance_id or catalog_item_id.")
        if self.credential_mode == "auto":
            if self.has_any_custom_credential():
                raise ValueError(
                    "Automatically chosen OAuth clients do not accept custom OAuth credentials."
                )
            return self
        self.validate_custom_credential_sources()
        return self


class OAuthAuthorizeResponse(BaseModel):
    authorize_url: str
    # The MCP instance, or the API connection this request created.
    connection_id: UUID


class OAuthFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=256)


class OAuthFinishResponse(BaseModel):
    # The frontend page to land on, with ``oauth=success`` or ``oauth=error``.
    location: str


class OAuthPreflightResponse(BaseModel):
    """What the UI needs before it can offer Connect.

    ``ready`` — Connect runs unattended, with the client ``credential_source``
    names: the operator's ``platform`` app, or one registered ``dynamic``-ally.
    ``oauth_app_required`` — ask for a client ID/secret first.
    ``unsupported`` — this cannot be authorized with OAuth; ``detail`` says why.
    """

    status: Literal["ready", "oauth_app_required", "unsupported"]
    credential_source: Literal["platform", "dynamic"] | None = None
    connected: bool
    detail: str = ""
    issuer: str | None = None
    authorization_endpoint: str | None = None
    scopes: list[str] = Field(default_factory=list)
    # The callback an OAuth app the user registers must allow.
    redirect_uri: str


@router.get(
    "/preflight",
    response_model=OAuthPreflightResponse,
    dependencies=[
        unrestricted(
            "workspace member; the workspace-scoped repositories are the boundary, and a "
            "platform app's credentials are never returned"
        )
    ],
)
async def oauth_preflight(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    instance_id: Annotated[UUID | None, Query(description="MCP instance to inspect")] = None,
    server_id: Annotated[
        UUID | None,
        Query(description="Catalog MCP spec to inspect before any instance exists"),
    ] = None,
    catalog_item_id: Annotated[
        UUID | None, Query(description="Catalog API to inspect before connecting it")
    ] = None,
) -> OAuthPreflightResponse:
    """Report whether a connection can be authorized, and with what.

    Every outcome is a 200: "this server has no OAuth" is an answer the UI
    renders, not a failure it has to decode.
    """
    if sum(target is not None for target in (instance_id, server_id, catalog_item_id)) != 1:
        raise HTTPException(
            status_code=422,
            detail="Pass exactly one of instance_id, server_id or catalog_item_id.",
        )
    target: PreflightTarget
    if instance_id is not None:
        target = await MCPInstanceTarget.load(instance_id, user_context, db_session)
    elif server_id is not None:
        target = await MCPSpecTarget.load(server_id, user_context, db_session)
    elif catalog_item_id is not None:
        target = await CatalogItemTarget.load(catalog_item_id, user_context, db_session)
    else:
        raise HTTPException(status_code=422, detail="No target to inspect.")

    answer = await oauth_connect.preflight(target)
    return OAuthPreflightResponse(
        status=answer.status,
        credential_source=answer.credential_source,
        connected=answer.connected,
        detail=answer.detail,
        issuer=answer.issuer,
        authorization_endpoint=answer.authorization_endpoint,
        scopes=list(answer.scopes),
        redirect_uri=callback_uri(),
    )


@router.post(
    "/authorize",
    response_model=OAuthAuthorizeResponse,
    dependencies=[
        enforced_in_handler(
            "edit on an MCP instance, whose credential the callback replaces; a catalog API "
            "connection is created for the caller by this request"
        )
    ],
)
async def oauth_authorize(
    body: OAuthAuthorizeRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    secret_catalog: SecretCatalogServiceDep,
) -> OAuthAuthorizeResponse:
    """Start a sign-in and return the provider's authorization URL to send the user to."""
    target: ConnectTarget
    if body.instance_id is not None:
        target = await MCPInstanceTarget.load(body.instance_id, user_context, db_session)
    elif body.catalog_item_id is not None:
        target = await CatalogItemTarget.load(body.catalog_item_id, user_context, db_session)
    else:
        raise HTTPException(status_code=422, detail="No target to authorize.")

    authorization = await oauth_connect.OAuthConnectService(
        db_session, user_context, secret_catalog
    ).authorize(
        target,
        credential_mode=body.credential_mode,
        custom=body,
        return_to=body.return_to,
    )
    return OAuthAuthorizeResponse(
        authorize_url=authorization.authorize_url, connection_id=authorization.connection_id
    )


@public_router.get(
    "/callback",
    dependencies=[
        enforced_in_handler("the one-time OAuth state token is the only credential it has")
    ],
)
async def oauth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
) -> RedirectResponse:
    """The provider's redirect back: park the code and send the browser to finish.

    Requires no session — the user is mid-redirect from the provider. Whoever
    follows a provider URL lands here, not only the person authorize returned
    it to, so nothing is attached until that person finishes.
    """
    location = await oauth_connect.receive(
        state=state, code=code, error=error, error_description=error_description
    )
    return RedirectResponse(url=location, status_code=302)


@principal_router.post(
    "/finish",
    response_model=OAuthFinishResponse,
    dependencies=[enforced_in_handler("only the person who started the sign-in may finish it")],
)
async def oauth_finish(
    body: OAuthFinishRequest,
    principal: PrincipalDep,
    db_session: DatabaseSessionDep,
) -> OAuthFinishResponse:
    """Exchange a returned code and attach the credential, for the flow's own starter."""
    location = await oauth_connect.finish(
        db_session,
        token=body.token,
        user_id=principal.user_id,
        reachable_workspaces=principal.accessible_workspaces or [],
    )
    return OAuthFinishResponse(location=location)
