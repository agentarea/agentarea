"""Provider API schemas with icon support."""

from pydantic import BaseModel, Field


class ProviderModel(BaseModel):
    """Schema for individual provider model."""

    name: str = Field(..., description="Model name")
    description: str = Field(..., description="Model description")
    context_window: int = Field(..., description="Model context window size")


class Provider(BaseModel):
    """Schema for AI provider with icon support."""

    id: str = Field(..., description="Unique provider identifier")
    name: str = Field(..., description="Provider display name")
    description: str = Field(..., description="Provider description")
    icon_url: str | None = Field(None, description="URL to provider icon")
    models: list[ProviderModel] = Field(..., description="Available models")


class ProvidersResponse(BaseModel):
    """Response schema for providers list."""

    providers: list[Provider] = Field(..., description="List of available providers")
