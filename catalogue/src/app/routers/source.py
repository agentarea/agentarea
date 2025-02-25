from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from ..config import get_db
from ..schemas.source import SourceCreate, SourceUpdate, SourceResponse
from ..services.source_service import SourceService
from pydantic import BaseModel

router = APIRouter(prefix="/sources", tags=["sources"])


class PresignedUrlRequest(BaseModel):
    filename: str
    file_type: str
    content_type: Optional[str] = None


class SourceAfterUploadRequest(BaseModel):
    source_id: str
    s3_key: str
    filename: str
    file_type: str
    content_type: str
    file_size: int
    description: Optional[str] = None
    owner: str = "system"


@router.post("/", response_model=SourceResponse)
async def create_source(source: SourceCreate, db: Session = Depends(get_db)):
    source_service = SourceService(db)
    return await source_service.create_source(source)


@router.get("/", response_model=List[SourceResponse])
async def list_sources(db: Session = Depends(get_db)):
    source_service = SourceService(db)
    return await source_service.list_sources()


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(source_id: str, db: Session = Depends(get_db)):
    source_service = SourceService(db)
    source = await source_service.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.put("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: str, source: SourceUpdate, db: Session = Depends(get_db)
):
    source_service = SourceService(db)
    updated_source = await source_service.update_source(source_id, source)
    if not updated_source:
        raise HTTPException(status_code=404, detail="Source not found")
    return updated_source


@router.delete("/{source_id}")
async def delete_source(source_id: str, db: Session = Depends(get_db)):
    source_service = SourceService(db)
    if not await source_service.delete_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    return {"message": "Source deleted successfully"}


@router.post("/upload", response_model=SourceResponse)
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form(...),
    description: Optional[str] = Form(None),
    owner: str = Form("system"),
    db: Session = Depends(get_db),
):
    """
    Upload a file to the system.

    The file will be stored in S3 and a source record will be created in the database.

    Args:
        file: The file to upload
        file_type: The type of file (e.g., csv, json, etc.)
        description: Optional description of the file
        owner: The owner of the file

    Returns:
        SourceResponse: The created source record
    """
    try:
        source_service = SourceService(db)
        return await source_service.upload_file(file, file_type, description, owner)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")


@router.post("/presigned-url", response_model=Dict[str, Any])
async def generate_presigned_url(
    request: PresignedUrlRequest, db: Session = Depends(get_db)
):
    """
    Generate a presigned URL for direct file upload to S3.

    Args:
        request: Contains filename, file_type, and optional content_type

    Returns:
        Dict containing presigned_url, source_id, and s3_key
    """
    try:
        source_service = SourceService(db)
        return await source_service.generate_presigned_url(
            request.filename, request.file_type, request.content_type
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating presigned URL: {str(e)}"
        )


@router.post("/after-upload", response_model=SourceResponse)
async def create_source_after_upload(
    request: SourceAfterUploadRequest, db: Session = Depends(get_db)
):
    """
    Create a source record after a file has been uploaded via presigned URL.

    Args:
        request: Contains details about the uploaded file

    Returns:
        SourceResponse: The created source record
    """
    try:
        source_service = SourceService(db)
        return await source_service.create_source_after_upload(
            request.source_id,
            request.s3_key,
            request.filename,
            request.file_type,
            request.content_type,
            request.file_size,
            request.description,
            request.owner,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error creating source after upload: {str(e)}"
        )
