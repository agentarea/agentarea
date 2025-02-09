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
async def upload_agent(
    agent_file: UploadFile,
    metadata_file: UploadFile,
):
    # Verify metadata file
    if not metadata_file.filename.endswith(
        ".yaml"
    ) and not metadata_file.filename.endswith(".yml"):
        raise HTTPException(400, "Metadata file must be YAML")

    try:
        agent_spec = await metadata_file.read()
        metadata_dict = yaml.safe_load(agent_spec)
        metadata = ModuleSpec(**metadata_dict)
    except Exception as e:
        raise HTTPException(400, f"Invalid metadata format: {str(e)}")

    # Process the agent upload
    try:
        agent_id = str(uuid.uuid4())
        response = await agent_service.save_agent(agent_id, agent_file, metadata)
        return response
    except Exception as e:
        raise HTTPException(500, f"Error uploading agent: {str(e)}")


@router.get("/", response_model=List[ModuleResponse])
async def list_agents():
    return await agent_service.list_agents()


@router.get("/{agent_id}", response_model=ModuleResponse)
async def get_agent(agent_id: str):
    agent = await agent_service.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent
