from importlib import import_module
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentarea_mcp.domain.verification_types import DEFAULT_VERIFICATION

# Ensure the referenced auth tables are registered on the shared metadata
# before SQLAlchemy resolves the auth_config_id foreign key on this model.
import_module("agentarea_mcp.domain.auth_models")


class MCPServerInstance(BaseModel, WorkspaceScopedMixin):
    __tablename__ = "mcp_server_instances"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    server_spec_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Nullable for external providers
    json_spec: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )  # Unified configuration storage
    verification: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=lambda: dict(DEFAULT_VERIFICATION)
    )
    last_dispatch: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    network_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    auth_config_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_auth_configs.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __init__(
        self,
        name: str,
        description: str | None = None,
        server_spec_id: str | None = None,
        json_spec: dict[str, Any] | None = None,
        verification: dict | None = None,
        network_scope: str = "private",
        workspace_id: str | None = None,
        created_by: str | None = None,
        auth_config_id: UUID | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = name
        self.description = description
        self.server_spec_id = server_spec_id
        self.json_spec = json_spec or {}
        self.verification = verification if verification is not None else dict(DEFAULT_VERIFICATION)
        self.network_scope = network_scope
        self.auth_config_id = auth_config_id
        if workspace_id is not None:
            self.workspace_id = workspace_id
        if created_by is not None:
            self.created_by = created_by

    @property
    def endpoint_url(self) -> str:
        instance_type = self.json_spec.get("type") or self.json_spec.get("server_type", "")
        if instance_type == "url":
            return self.json_spec.get("endpoint_url", "")
        if instance_type in ("docker", "command"):
            # Prefer a full URL the Go manager returned (K8s backend reports
            # `http://mcp-<name>.<ns>.svc.cluster.local:<port>`). Docker backend
            # returns a traefik path like `/mcp/<slug>` — ignore those and fall
            # back to the direct-container address.
            resolved = self.json_spec.get("internal_url")
            if isinstance(resolved, str) and "://" in resolved:
                return resolved
            port = self.json_spec.get("port") or 8000
            return f"http://mcp-{self.id}:{port}"
        raise ValueError("bundle has no endpoint_url")

    def get_configured_env_vars(self) -> list[str]:
        """Get list of environment variable names configured for this instance.

        Returns:
            List of environment variable names from the env_vars section of json_spec
        """
        env_vars = self.json_spec.get("env_vars", [])
        if isinstance(env_vars, list):
            return [str(var) for var in env_vars]
        return []

    def get_available_tools(self) -> list[dict[str, Any]]:
        """Get list of available tools for this MCP server instance.

        Returns:
            List of tool dictionaries with name, description, and schema
        """
        return self.json_spec.get("available_tools", [])

    def set_available_tools(self, tools: list[dict[str, Any]]) -> None:
        """Set the available tools for this MCP server instance.

        Args:
            tools: List of tool dictionaries with name, description, and schema
        """
        if self.json_spec is None:
            self.json_spec = {}
        self.json_spec["available_tools"] = tools
