from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from ..schemas.source import (
    SourceSpecification,
    SourceSpecificationResponse,
    SourceSpecificationRequest,
    SourceCategory,
)
from ..services.source_specification_service import SourceSpecificationService

router = APIRouter(prefix="/source-specifications", tags=["source-specifications"])


@router.get("/", response_model=SourceSpecificationResponse)
async def list_source_specifications(
    request: Optional[SourceSpecificationRequest] = None,
):
    """
    List all available source specifications.
    Optionally filter by category.
    """
    service = SourceSpecificationService()
    category = request.category if request else None
    specifications = service.get_specifications(category)
    return SourceSpecificationResponse(specifications=specifications)


@router.get("/{spec_id}", response_model=SourceSpecification)
async def get_source_specification(spec_id: str):
    """
    Get a specific source specification by ID.
    """
    service = SourceSpecificationService()
    specification = service.get_specification_by_id(spec_id)
    if not specification:
        raise HTTPException(status_code=404, detail="Source specification not found")
    return specification
