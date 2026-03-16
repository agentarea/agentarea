"""API endpoints for OpenAPI connections."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agentarea_api.api.deps.services import get_openapi_connection_service
from agentarea_openapi.application.service import OpenAPIConnectionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/openapi-connections", tags=["openapi-connections"])


class OpenAPIConnectionCreate(BaseModel):
    name: str = Field(..., max_length=255)
    base_url: str = Field(..., max_length=500)
    description: str | None = None
    spec_url: str | None = None
    spec_content: dict[str, Any] | None = None
    auth_config_id: UUID | None = None


class OpenAPIConnectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    base_url: str | None = None
    spec_url: str | None = None
    spec_content: dict[str, Any] | None = None
    auth_config_id: UUID | None = None


class OpenAPIConnectionResponse(BaseModel):
    id: UUID
    name: str
    base_url: str
    description: str | None = None
    spec_url: str | None = None
    auth_config_id: UUID | None = None
    available_tools: list[dict[str, Any]] = []
    status: str
    created_at: Any
    updated_at: Any

    model_config = {"from_attributes": True}


@router.post("/", response_model=OpenAPIConnectionResponse, status_code=201)
async def create_connection(
    request: OpenAPIConnectionCreate,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    try:
        conn = await service.create_connection(
            name=request.name,
            base_url=request.base_url,
            description=request.description,
            spec_url=request.spec_url,
            spec_content=request.spec_content,
            auth_config_id=request.auth_config_id,
        )
        return OpenAPIConnectionResponse.model_validate(conn)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
    return [OpenAPIConnectionResponse.model_validate(c) for c in connections]


@router.get("/{connection_id}", response_model=OpenAPIConnectionResponse)
async def get_connection(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    conn = await service.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return OpenAPIConnectionResponse.model_validate(conn)


@router.patch("/{connection_id}", response_model=OpenAPIConnectionResponse)
async def update_connection(
    connection_id: UUID,
    request: OpenAPIConnectionUpdate,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    conn = await service.update_connection(connection_id, **fields)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return OpenAPIConnectionResponse.model_validate(conn)


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


@router.post("/{connection_id}/test")
async def test_connection(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    try:
        return await service.test_connection(connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
