"""Bundle import endpoints: analyze a source and install a bundle."""

from typing import Annotated, Any

from agentarea_api.api.deps.services import (
    AgentServiceDep,
    MCPServerInstanceServiceDep,
    MCPServerServiceDep,
    SkillServiceDep,
    get_trigger_service,
)
from agentarea_bundles.application.analyzer import BundleParseError
from agentarea_bundles.application.installer import BundleInstallError
from agentarea_bundles.application.service import BundleService
from agentarea_bundles.schemas.bundle import Bundle
from agentarea_bundles.schemas.preview import ImportPreview
from agentarea_bundles.schemas.result import InstallResult
from agentarea_common.base import RepositoryFactoryDep
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/bundles", tags=["bundles"])


# ============================================================================
# Service Dependency
# ============================================================================


async def get_bundle_service(
    repository_factory: RepositoryFactoryDep,
    agent_service: AgentServiceDep,
    mcp_server_service: MCPServerServiceDep,
    mcp_instance_service: MCPServerInstanceServiceDep,
    skill_service: SkillServiceDep,
    trigger_service: Annotated[Any, Depends(get_trigger_service)],
) -> BundleService:
    """Compose BundleService from the existing domain services."""
    return BundleService(
        repository_factory=repository_factory,
        agent_service=agent_service,
        mcp_server_service=mcp_server_service,
        mcp_instance_service=mcp_instance_service,
        skill_service=skill_service,
        trigger_service=trigger_service,
    )


BundleServiceDep = Annotated[BundleService, Depends(get_bundle_service)]


# ============================================================================
# Request models
# ============================================================================


class AnalyzeRequest(BaseModel):
    """Analyze raw bundle source (YAML or JSON) into an import preview."""

    source: str = Field(min_length=1, description="Raw bundle source text (YAML or JSON).")


class InstallRequest(BaseModel):
    """Install a (previously analyzed, possibly edited) canonical bundle."""

    bundle: Bundle
    setup_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Values for the bundle's setup fields, keyed by setup field key.",
    )


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/analyze", response_model=ImportPreview)
async def analyze_bundle(
    body: AnalyzeRequest,
    service: BundleServiceDep,
) -> ImportPreview:
    """Parse and analyze a bundle source, returning a non-destructive preview."""
    try:
        return await service.analyze_text(body.source)
    except BundleParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/install", response_model=InstallResult)
async def install_bundle(
    body: InstallRequest,
    service: BundleServiceDep,
) -> InstallResult:
    """Install a canonical bundle: MCP instances, skills, agents and automations."""
    try:
        return await service.install(body.bundle, body.setup_values)
    except BundleInstallError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc),
                "issues": [i.model_dump(mode="json") for i in exc.issues],
            },
        ) from exc
