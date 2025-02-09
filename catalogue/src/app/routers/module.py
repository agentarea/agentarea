from fastapi import APIRouter, UploadFile, HTTPException
import json
import yaml
import uuid
from typing import List

from ..schemas import ModuleSpec, ModuleResponse
from ..services import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])
agent_service = AgentService()


@router.post("/", response_model=ModuleResponse)
async def upload_module(
    module_file: UploadFile,
    spec_file: UploadFile,
):
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
        response = await agent_service.save_module(module_id, module_file, metadata)
        return response
    except Exception as e:
        raise HTTPException(500, f"Error uploading agent: {str(e)}")


@router.get("/", response_model=List[ModuleResponse])
async def list_modules():
    return await agent_service.list_modules()


@router.get("/{module_id}", response_model=ModuleResponse)
async def get_module(module_id: str):
    module = await agent_service.get_module(module_id)
    if not module:
        raise HTTPException(404, "Module not found")
    return module
