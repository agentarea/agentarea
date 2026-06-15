"""Bundle import endpoints: analyze a source and install a bundle."""

import logging
from typing import Annotated, Any

import httpx
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
from agentarea_common.config import get_settings
from agentarea_openapi.application.url_validator import validate_url
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bundles", tags=["bundles"])

# A bundle is a small YAML/JSON document; cap the fetched body to the same 5MB
# ceiling the OpenAPI spec fetcher uses so a hostile URL can't exhaust memory.
_MAX_BUNDLE_BYTES = 5 * 1024 * 1024
_FETCH_TIMEOUT_SECONDS = 10.0


async def fetch_bundle_source(
    url: str,
    *,
    allow_private: bool,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Fetch raw bundle text from a URL behind the shared SSRF guard.

    Mirrors the outbound-fetch discipline of the OpenAPI/MCP endpoints:
    `validate_url` vets the scheme and rejects private/internal targets before
    any request is made, redirects are not followed (a redirect could bounce to
    an internal IP that bypasses the up-front check), and the body is size-capped.

    Raises:
        ValueError: URL is unsafe (bad scheme / private IP) or body too large.
        httpx.HTTPStatusError: the URL returned a non-2xx (including redirects).
        httpx.RequestError: the request could not be completed.
    """
    validate_url(url, allow_private=allow_private)
    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        transport=transport,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        if len(response.content) > _MAX_BUNDLE_BYTES:
            raise ValueError("bundle source exceeds 5MB limit")
        return response.text


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
    """Analyze a bundle into an import preview.

    Provide exactly one of ``source`` (pasted text) or ``source_url`` (a URL the
    server fetches behind the SSRF guard). ``source_url`` is what a landing-page
    deep-link (`/bundles/import?src=<url>`) uses for one-click installs.
    """

    source: str | None = Field(
        default=None, description="Raw bundle source text (YAML or JSON)."
    )
    source_url: str | None = Field(
        default=None, description="URL to fetch raw bundle source from (YAML or JSON)."
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "AnalyzeRequest":
        provided = [s for s in (self.source, self.source_url) if s and s.strip()]
        if len(provided) != 1:
            raise ValueError("provide exactly one of 'source' or 'source_url'")
        return self


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
    source = body.source
    if body.source_url:
        allow_private = get_settings().mcp.ALLOW_PRIVATE_URLS
        try:
            source = await fetch_bundle_source(body.source_url, allow_private=allow_private)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"bundle URL returned HTTP {exc.response.status_code}",
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Failed to fetch bundle from %s: %s", body.source_url, exc)
            raise HTTPException(
                status_code=400, detail="failed to fetch bundle from the provided URL"
            ) from exc

    try:
        return await service.analyze_text(source or "")
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
