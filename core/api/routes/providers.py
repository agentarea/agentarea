"""Provider API routes with static file support."""

from typing import Any

import yaml
from core.api.schemas.provider_schema import Provider, ProvidersResponse
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def load_providers_from_yaml() -> dict[str, Any]:
    """Load providers from YAML file."""
    with open("data/providers.yaml") as f:
        return yaml.safe_load(f)


def generate_icon_url(request: Request, icon_id: str) -> str:
    """Generate static file URL for icon."""
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/static/icons/providers/{icon_id}.svg"


@router.get("/providers", response_model=ProvidersResponse)
async def get_providers(request: Request):
    """Get all available AI providers with static icon URLs.

    Icons are served as static files from /static/icons/providers/
    """
    providers_data = load_providers_from_yaml()

    providers = []
    for provider_info in providers_data["providers"].values():
        # Generate static file URL if icon identifier exists
        icon_url = None
        if "icon" in provider_info:
            icon_url = generate_icon_url(request, provider_info["icon"])

        provider = Provider(
            id=provider_info["id"],
            name=provider_info["name"],
            description=provider_info["description"],
            icon_url=icon_url,
            models=provider_info.get("models", []),
        )
        providers.append(provider)

    return ProvidersResponse(providers=providers)


@router.get("/providers/{provider_id}", response_model=Provider)
async def get_provider(provider_id: str, request: Request):
    """Get a specific provider by ID with static icon URL."""
    providers_data = load_providers_from_yaml()

    # Find provider by ID
    for provider_info in providers_data["providers"].values():
        if provider_info["id"] == provider_id:
            icon_url = None
            if "icon" in provider_info:
                icon_url = generate_icon_url(request, provider_info["icon"])

            return Provider(
                id=provider_info["id"],
                name=provider_info["name"],
                description=provider_info["description"],
                icon_url=icon_url,
                models=provider_info.get("models", []),
            )

    raise HTTPException(status_code=404, detail="Provider not found")
