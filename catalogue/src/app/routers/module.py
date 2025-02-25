from fastapi import APIRouter, UploadFile, HTTPException, Depends
import json
import yaml
import uuid
from typing import List
from sqlalchemy.orm import Session

from ..config import get_db

from ..schemas.module import ModuleSpec, ModuleResponse
from ..services.module_service import ModuleService

# Изменяем префикс, убирая /modules, так как он будет добавлен в основном роутере
router = APIRouter(tags=["modules"])


@router.post("/", response_model=ModuleResponse)
async def upload_module(spec_file: UploadFile, db: Session = Depends(get_db)):
    # Create service instance with db session
    module_service = ModuleService(db=db)

    # Verify metadata file
    if not spec_file.filename.endswith(".yaml") and not spec_file.filename.endswith(
        ".yml"
    ):
        raise HTTPException(400, "Metadata file must be YAML")

    try:
        spec = await spec_file.read()
        spec_dict = yaml.safe_load(spec)
        metadata = ModuleSpec(**spec_dict)
    except Exception as e:
        raise HTTPException(400, f"Invalid metadata format: {str(e)}")

    # Process the agent upload
    try:
        module_id = str(uuid.uuid4())
        response = await module_service.save_module(module_id, metadata)
        return response
    except Exception as e:
        raise HTTPException(500, f"Error uploading module: {str(e)}")


@router.get("/", response_model=List[ModuleResponse])
async def list_modules(db: Session = Depends(get_db)):
    module_service = ModuleService(db=db)
    return await module_service.list_modules()


@router.get("/{module_id}", response_model=ModuleResponse)
async def get_module(module_id: str, db: Session = Depends(get_db)):
    module_service = ModuleService(db=db)
    module = await module_service.get_module(module_id)
    if not module:
        raise HTTPException(404, "Module not found")
    return module
