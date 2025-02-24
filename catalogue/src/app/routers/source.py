from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ..config import get_db
from ..schemas import SourceCreate, SourceUpdate, SourceResponse
from ..services import SourceService

router = APIRouter(prefix="/sources", tags=["sources"])

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
async def update_source(source_id: str, source: SourceUpdate, db: Session = Depends(get_db)):
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