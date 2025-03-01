import uuid
from fastapi import APIRouter, HTTPException, Depends, Path, Query
from typing import List, Optional
from sqlalchemy.orm import Session

from ..schemas.model import (
    ConnectionStatus,
    CreateModelReferenceRequest,
    ModelInstance,
    CreateModelInstance,
    ModelReference,
    ModelScope,
)

from ..services.model_service import ModelService
from ..models.model import (
    ModelInstance as DBModelInstance,
    ModelReference as DBModelReference,
)
from .dependencies import get_model_service

# Изменяем префикс, убирая /llm, так как он будет добавлен в основном роутере
router = APIRouter(tags=["model"])


@router.get(
    "/",
    response_model=List[ModelInstance],
    summary="Get Model list",
    description="Returns a list of all available Models in the system",
)
async def get_model_instances(
    model_service: ModelService = Depends(get_model_service),
):
    """
    Get a list of all available Model types in the system
    """
    return await model_service.get_instances()


@router.post(
    "/",
    response_model=ModelInstance,
    summary="Add new Model",
    description="Adds a new Model to the system",
)
async def add_model_instance(
    model: CreateModelInstance,
    model_service: ModelService = Depends(get_model_service),
):
    """
    Add a new Model to the system
    """

    return await model_service.add_instance(DBModelInstance(**model.model_dump()))


@router.get(
    "/references",
    response_model=List[ModelReference],
    summary="Get references list",
    description="Returns a list of all references with optional filtering by type and scope",
)
async def get_model_references(
    scope: Optional[ModelScope] = Query(None, description="Filter by scope"),
    model_service: ModelService = Depends(get_model_service),
):
    """
    Get a list of all configured Model instances with filtering options
    """
    # TODO: Implement instances retrieval with filtering
    return await model_service.get_references(scope)


@router.post(
    "/references",
    response_model=ModelReference,
    summary="Create new reference",
    description="Creates a new reference based on existing Model instance",
)
async def create_model_reference(
    reference_data: CreateModelReferenceRequest,
    model_service: ModelService = Depends(get_model_service),
):
    """
    Create a new Model instance based on catalog with specified settings
    """
    reference = await model_service.create_reference(
        instance_id=reference_data.instance_id,
        name=reference_data.name,
        settings=reference_data.settings.model_dump(),
        scope=reference_data.scope,
    )
    return reference


@router.get(
    "/references/{reference_id}",
    response_model=ModelReference,
    summary="Get reference",
    description="Returns information about specific reference by its ID",
)
async def get_model_reference(
    reference_id: str = Path(..., description="Reference ID to get"),
    model_service: ModelService = Depends(get_model_service),
):
    """
    Get information about specific Model instance
    """
    reference = await model_service.get_reference(reference_id)
    return reference


@router.delete(
    "/references/{reference_id}",
    summary="Delete reference",
    description="Deletes specified reference from the system",
)
async def delete_model_reference(
    reference_id: str = Path(..., description="Reference ID to delete"),
    model_service: ModelService = Depends(get_model_service),
):
    """
    Delete Model instance
    """
    return await model_service.delete_reference(reference_id)


@router.post(
    "/references/{reference_id}/check-connection",
    response_model=ConnectionStatus,
    summary="Check connection",
    description="Checks connection to Model and returns connection status",
)
async def check_model_connection(
    reference_id: str = Path(..., description="Reference ID to check"),
    model_service: ModelService = Depends(get_model_service),
):
    """
    Check Model connection and its functionality.
    Returns connection status, message, latency and additional information.
    """
    return await model_service.check_connection(reference_id)
    # TODO: Implement connection check logic:
    # 1. Get Model instance by id
    # 2. Try to connect based on type (API/LOCAL)
    # 3. Measure latency
    # 4. Run simple test prompt
    # 5. Return connection status
    pass
