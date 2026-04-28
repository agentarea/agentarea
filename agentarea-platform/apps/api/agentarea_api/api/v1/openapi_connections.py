"""API endpoints for OpenAPI connections."""

import json
import logging
from typing import Any
from uuid import UUID

import httpx
from agentarea_api.api.deps.services import get_openapi_connection_service
from agentarea_common.config import get_settings
from agentarea_openapi.application.service import OpenAPIConnectionService, fetch_and_parse_spec
from agentarea_openapi.application.spec_parser import parse_openapi_spec
from agentarea_openapi.application.url_validator import validate_url
from agentarea_openapi.schemas.dto import (
    HeaderOutput,
    OpenAPIConnectionCreate,
    OpenAPIConnectionUpdate,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/openapi-connections", tags=["openapi-connections"])


class OpenAPIConnectionResponse(BaseModel):
    id: UUID
    name: str
    base_url: str
    description: str | None = None
    spec_url: str | None = None
    auth_config_id: UUID | None = None
    custom_headers: list[HeaderOutput] | None = None
    available_tools: list[dict[str, Any]] = []
    status: str
    created_at: Any
    updated_at: Any

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


class SpecPreviewRequest(BaseModel):
    spec_url: str | None = None
    spec_content: dict[str, Any] | None = None

    @field_validator("spec_url")
    @classmethod
    def validate_spec_url(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                validate_url(v, allow_private=get_settings().mcp.ALLOW_PRIVATE_URLS)
            except ValueError as e:
                raise ValueError(str(e)) from e
        return v


class SpecPreviewResponse(BaseModel):
    title: str | None = None
    description: str | None = None
    base_url: str | None = None
    version: str | None = None
    tools: list[dict[str, str]] = []


@router.post("/preview-spec", response_model=SpecPreviewResponse)
async def preview_spec(
    request: SpecPreviewRequest,
    _service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    """Fetch/parse an OpenAPI spec and return metadata + tools without creating a connection.

    The service dependency ensures authentication is enforced.
    """
    settings = get_settings()
    allow_private = settings.mcp.ALLOW_PRIVATE_URLS

    spec: dict[str, Any] | None = request.spec_content

    if spec is not None:
        if len(json.dumps(spec)) >= 5_000_000:
            raise HTTPException(status_code=400, detail="spec_content exceeds 5MB limit.")

    if not spec and request.spec_url:
        try:
            validate_url(request.spec_url, allow_private=allow_private)
            spec = await fetch_and_parse_spec(
                request.spec_url,
                allow_private=allow_private,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except httpx.RequestError as e:
            logger.error("Failed to fetch spec from %s: %s", request.spec_url, e)
            raise HTTPException(
                status_code=400, detail="Failed to fetch spec from the provided URL."
            ) from e
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=400, detail=f"Spec URL returned HTTP {e.response.status_code}"
            ) from e

    if not spec:
        raise HTTPException(status_code=400, detail="Provide spec_url or spec_content")

    try:
        tools = parse_openapi_spec(spec)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    info = spec.get("info", {})
    servers = spec.get("servers", [])
    base_url = servers[0].get("url") if servers else None

    return SpecPreviewResponse(
        title=info.get("title"),
        description=info.get("description"),
        base_url=base_url,
        version=info.get("version"),
        tools=[{"name": t["name"], "description": t.get("description", "")} for t in tools],
    )


@router.post("/", response_model=OpenAPIConnectionResponse, status_code=201)
async def create_connection(
    request: OpenAPIConnectionCreate,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    try:
        conn = await service.create_connection(request)
        resp = OpenAPIConnectionResponse.model_validate(conn)
        resp.custom_headers = _format_headers(conn.custom_headers)
        return resp
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch spec: HTTP {e.response.status_code}",
        ) from e
    except httpx.RequestError as e:
        logger.error("Failed to fetch spec during connection create: %s", e)
        raise HTTPException(
            status_code=400, detail="Failed to fetch spec from the provided URL."
        ) from e


@router.get("/", response_model=list[OpenAPIConnectionResponse])
async def list_connections(
    status: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    connections, _total = await service.list_connections(
        status=status, search=search, limit=limit, offset=offset
    )
    results = []
    for c in connections:
        resp = OpenAPIConnectionResponse.model_validate(c)
        resp.custom_headers = _format_headers(c.custom_headers)
        results.append(resp)
    return results


@router.get("/{connection_id}", response_model=OpenAPIConnectionResponse)
async def get_connection(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    conn = await service.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    resp = OpenAPIConnectionResponse.model_validate(conn)
    resp.custom_headers = _format_headers(conn.custom_headers)
    return resp


@router.patch("/{connection_id}", response_model=OpenAPIConnectionResponse)
async def update_connection(
    connection_id: UUID,
    request: OpenAPIConnectionUpdate,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    if not request.model_fields_set:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        conn = await service.update_connection(connection_id, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    resp = OpenAPIConnectionResponse.model_validate(conn)
    resp.custom_headers = _format_headers(conn.custom_headers)
    return resp


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    deleted = await service.delete_connection(connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Connection not found")


@router.post("/{connection_id}/discover-tools")
async def discover_tools(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    try:
        return await service.discover_tools(connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to discover tools for {connection_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to discover tools") from e
