import uuid
from fastapi import APIRouter, HTTPException, Depends, Path, Query
from typing import List, Optional
from sqlalchemy.orm import Session

from ..schemas.llm import (
    ConnectionStatus,
    CreateLLMReferenceRequest,
    LLMInstance,
    CreateLLMInstance,
    LLMReference,
    LLMScope,
)

from ..services.llm_service import LLMService
from ..models.llm import LLMInstance as DBLLMInstance, LLMReference as DBLLMReference
from .dependencies import get_llm_service

# Изменяем префикс, убирая /llm, так как он будет добавлен в основном роутере
router = APIRouter(tags=["llm"])


@router.get(
    "/",
    response_model=List[LLMInstance],
    summary="Get LLM list",
    description="Returns a list of all available LLMs in the system",
)
async def get_llm_instances(
    # inject service
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Get a list of all available LLM types in the system
    """
    # TODO: Implement catalog retrieval from database
    return await llm_service.get_instances()


@router.post(
    "/",
    response_model=LLMInstance,
    summary="Add new LLM",
    description="Adds a new LLM to the system",
)
async def add_llm_instance(
    llm: CreateLLMInstance,
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Add a new LLM to the system
    """

    return await llm_service.add_instance(DBLLMInstance(**llm.model_dump()))


@router.get(
    "/references",
    response_model=List[LLMReference],
    summary="Get references list",
    description="Returns a list of all references with optional filtering by type and scope",
)
async def get_llm_references(
    scope: Optional[LLMScope] = Query(None, description="Filter by scope"),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Get a list of all configured LLM instances with filtering options
    """
    # TODO: Implement instances retrieval with filtering
    return await llm_service.get_references(scope)


@router.post(
    "/references",
    response_model=LLMReference,
    summary="Create new reference",
    description="Creates a new reference based on existing LLM instance",
)
async def create_llm_reference(
    reference_data: CreateLLMReferenceRequest,
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Create a new LLM instance based on catalog with specified settings
    """
    reference = await llm_service.create_reference(
        instance_id=reference_data.instance_id,
        name=reference_data.name,
        settings=reference_data.settings.model_dump(),
        scope=reference_data.scope,
    )
    return reference


@router.get(
    "/references/{reference_id}",
    response_model=LLMReference,
    summary="Get reference",
    description="Returns information about specific reference by its ID",
)
async def get_llm_reference(
    reference_id: str = Path(..., description="Reference ID to get"),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Get information about specific LLM instance
    """
    reference = await llm_service.get_reference(reference_id)
    return reference


@router.delete(
    "/references/{reference_id}",
    summary="Delete reference",
    description="Deletes specified reference from the system",
)
async def delete_llm_reference(
    reference_id: str = Path(..., description="Reference ID to delete"),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Delete LLM instance
    """
    return await llm_service.delete_reference(reference_id)


@router.post(
    "/references/{reference_id}/check-connection",
    response_model=ConnectionStatus,
    summary="Check connection",
    description="Checks connection to LLM and returns connection status",
)
async def check_llm_connection(
    reference_id: str = Path(..., description="Reference ID to check"),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Check LLM connection and its functionality.
    Returns connection status, message, latency and additional information.
    """
    return await llm_service.check_connection(reference_id)
    # TODO: Implement connection check logic:
    # 1. Get LLM instance by id
    # 2. Try to connect based on type (API/LOCAL)
    # 3. Measure latency
    # 4. Run simple test prompt
    # 5. Return connection status
    pass
