"""Client (agent-proxy) CRUD DTOs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClientCreate(BaseModel):
    """Payload for registering a client (agent-proxy)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    kind: str = Field(default="harness", max_length=32)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v


class ClientUpdate(BaseModel):
    """Patch payload for a client. Unset fields remain unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    kind: str | None = Field(default=None, max_length=32)
