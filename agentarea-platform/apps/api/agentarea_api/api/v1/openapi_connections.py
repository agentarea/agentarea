"""API endpoints for OpenAPI connections."""

import json
import logging
from typing import Any, Literal
from uuid import UUID

from agentarea_api.api.deps.services import DatabaseSessionDep, get_openapi_connection_service
from agentarea_api.catalog_api import CatalogApiItem, load_catalog_api_item
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import requires, unrestricted
from agentarea_common.base.pagination import MAX_OFFSET
from agentarea_common.utils.types import UtcDatetime
from agentarea_common.utils.url_safety import OutboundPolicy
from agentarea_openapi.application.catalog_key_template import (
    CatalogKeyTemplate,
    CatalogKeyTemplateError,
    catalog_key_credentials,
    catalog_key_template,
)
from agentarea_openapi.application.service import OpenAPIConnectionService, fetch_and_parse_spec
from agentarea_openapi.application.spec_parser import openapi_spec_info, parse_openapi_spec
from agentarea_openapi.application.url_validator import validate_url
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_openapi.schemas.dto import (
    HeaderOutput,
    OpenAPIConnectionCreate,
    OpenAPIConnectionUpdate,
    QueryParamOutput,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/openapi-connections", tags=["openapi-connections"])


class OpenAPIToolResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")


class OpenAPIConnectionResponse(BaseModel):
    id: UUID
    name: str
    base_url: str | None
    description: str | None = None
    spec_url: str | None = None
    auth_config_id: UUID | None = None
    registry_item_id: UUID | None = None
    custom_headers: list[HeaderOutput] | None = None
    custom_query_params: list[QueryParamOutput] | None = None
    url_variables: list[str] | None = None
    available_tools: list[OpenAPIToolResponse]
    status: str
    last_dispatch: dict[str, Any] | None = None
    # A member-set cost that wins over the connector's (wiki ADR-0038 §2.3).
    cost: dict[str, Any] | None = None
    managed_by: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = {"from_attributes": True}


def _format_headers(raw: list[dict[str, Any]] | None) -> list[HeaderOutput] | None:
    """Convert stored header metadata to response format (mask secret values)."""
    if not raw:
        return None
    return [
        HeaderOutput(
            name=h["name"],
            secret=h.get("secret", False),
            value=h.get("value") if not h.get("secret") else None,
        )
        for h in raw
    ]


def _format_query_params(raw: list[dict[str, Any]] | None) -> list[QueryParamOutput] | None:
    """Convert stored query parameter metadata to response format (mask secret values)."""
    if not raw:
        return None
    return [
        QueryParamOutput(
            name=p["name"],
            secret=p.get("secret", False),
            value=p.get("value") if not p.get("secret") else None,
        )
        for p in raw
    ]


def _connection_response(conn: OpenAPIConnection) -> OpenAPIConnectionResponse:
    resp = OpenAPIConnectionResponse.model_validate(conn)
    resp.base_url = conn.visible_base_url
    resp.custom_headers = _format_headers(conn.custom_headers)
    resp.custom_query_params = _format_query_params(conn.custom_query_params)
    return resp


class SpecPreviewRequest(BaseModel):
    spec_url: str | None = None
    spec_content: dict[str, Any] | None = None

    @field_validator("spec_url")
    @classmethod
    def validate_spec_url(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                validate_url(v, policy=OutboundPolicy.from_env())
            except ValueError as e:
                raise ValueError(str(e)) from e
        return v


class SpecPreviewResponse(BaseModel):
    title: str | None = None
    description: str | None = None
    base_url: str | None = None
    version: str | None = None
    tools: list[dict[str, str]] = []


@router.post(
    "/preview-spec",
    response_model=SpecPreviewResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def preview_spec(
    request: SpecPreviewRequest,
    _service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    """Fetch/parse an OpenAPI spec and return metadata + tools without creating a connection.

    The service dependency ensures authentication is enforced.
    """
    policy = OutboundPolicy.from_env()

    spec: dict[str, Any] | None = request.spec_content

    if spec is not None:
        if len(json.dumps(spec)) >= 5_000_000:
            raise HTTPException(status_code=400, detail="spec_content exceeds 5MB limit.")

    if not spec and request.spec_url:
        try:
            validate_url(request.spec_url, policy=policy)
            spec = await fetch_and_parse_spec(request.spec_url, policy=policy)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    if not spec:
        raise HTTPException(status_code=400, detail="Provide spec_url or spec_content")

    try:
        tools = parse_openapi_spec(spec)
        info = openapi_spec_info(spec)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return SpecPreviewResponse(
        **info,
        tools=[{"name": t["name"], "description": t.get("description", "")} for t in tools],
    )


@router.post(
    "/",
    response_model=OpenAPIConnectionResponse,
    status_code=201,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_connection(
    request: OpenAPIConnectionCreate,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    try:
        conn = await service.create_connection(request)
        return _connection_response(conn)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class CatalogKeyFieldResponse(BaseModel):
    """One value a catalog API needs before it can be called."""

    name: str = Field(description="Header or query parameter the value is sent in.")
    location: Literal["header", "query"]
    label: str = Field(description="What the vendor calls it, for the form.")
    description: str | None = None


class CatalogConnectFormResponse(BaseModel):
    """How a catalog API is connected: by signing in, or by entering its keys."""

    catalog_item_id: UUID
    name: str
    description: str | None = None
    auth: Literal["oauth", "api_key"]
    fields: list[CatalogKeyFieldResponse] = Field(default_factory=list)


class CatalogKeyValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=256)
    value: str = Field(max_length=8192)


class CatalogConnectRequest(BaseModel):
    """The keys a catalog API asks for, one per field of its connect form."""

    model_config = ConfigDict(extra="forbid")

    credentials: list[CatalogKeyValue] = Field(min_length=1, max_length=16)


async def _catalog_key_item(
    catalog_item_id: UUID, user_context: UserContext, session: AsyncSession
) -> tuple[CatalogApiItem, CatalogKeyTemplate | None]:
    catalog = await load_catalog_api_item(catalog_item_id, user_context, session)
    try:
        return catalog, catalog_key_template(catalog.spec)
    except CatalogKeyTemplateError as e:
        logger.exception("Catalog item %s has a malformed key template", catalog_item_id)
        raise HTTPException(
            status_code=500, detail="This catalog connection is misconfigured"
        ) from e


@router.get(
    "/from-catalog/{catalog_item_id}",
    response_model=CatalogConnectFormResponse,
    dependencies=[
        unrestricted("workspace member; the catalog item is read through the scoped registry")
    ],
)
async def get_catalog_connect_form(
    catalog_item_id: UUID, user_context: UserContextDep, db_session: DatabaseSessionDep
) -> CatalogConnectFormResponse:
    """What connecting this catalog API asks for: a sign-in, or the keys listed in ``fields``."""
    catalog, template = await _catalog_key_item(catalog_item_id, user_context, db_session)
    return CatalogConnectFormResponse(
        catalog_item_id=catalog.id,
        name=catalog.name,
        description=catalog.description,
        auth="api_key" if template else "oauth",
        fields=[
            CatalogKeyFieldResponse(
                name=f.name, location=f.location, label=f.label, description=f.description
            )
            for f in (template.fields if template else ())
        ],
    )


@router.post(
    "/from-catalog/{catalog_item_id}",
    response_model=OpenAPIConnectionResponse,
    status_code=201,
    dependencies=[
        unrestricted("workspace member; the connection is created for the caller, in scope")
    ],
)
async def connect_catalog_api(
    catalog_item_id: UUID,
    request: CatalogConnectRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    """Connect a catalog API with its keys; each call makes another connection."""
    catalog, template = await _catalog_key_item(catalog_item_id, user_context, db_session)
    if template is None:
        raise HTTPException(status_code=400, detail="This catalog API connects by signing in")
    values = {c.name: c.value for c in request.credentials}
    if len(values) != len(request.credentials):
        raise HTTPException(status_code=400, detail="A field was given twice")
    try:
        headers, params = catalog_key_credentials(template, values)
        conn = await service.create_connection(
            OpenAPIConnectionCreate(
                name=catalog.name,
                description=catalog.description,
                base_url=str(catalog.spec.get("base_url") or ""),
                spec_url=catalog.spec.get("spec_url"),
                spec_content=catalog.spec.get("spec_content"),
                custom_headers=headers or None,
                custom_query_params=params or None,
            ),
            registry_item_id=catalog.id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _connection_response(conn)


@router.get(
    "/",
    response_model=list[OpenAPIConnectionResponse],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_connections(
    status: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    connections, _total = await service.list_connections(
        status=status, search=search, limit=limit, offset=offset
    )
    return [_connection_response(c) for c in connections]


@router.get(
    "/{connection_id}",
    response_model=OpenAPIConnectionResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_connection(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    conn = await service.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return _connection_response(conn)


@router.patch(
    "/{connection_id}",
    response_model=OpenAPIConnectionResponse,
    dependencies=[requires("edit", "openapi_connection", id_param="connection_id")],
)
async def update_connection(
    connection_id: UUID,
    request: OpenAPIConnectionUpdate,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    if not request.model_fields_set:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        conn = await service.update_connection(connection_id, request)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return _connection_response(conn)


@router.delete(
    "/{connection_id}",
    status_code=204,
    dependencies=[requires("delete", "openapi_connection", id_param="connection_id")],
)
async def delete_connection(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    deleted = await service.delete_connection(connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Connection not found")


@router.post(
    "/{connection_id}/discover-tools",
    dependencies=[requires("edit", "openapi_connection", id_param="connection_id")],
)
async def discover_tools(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    try:
        return await service.discover_tools(connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Failed to discover tools for {connection_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to discover tools") from e
