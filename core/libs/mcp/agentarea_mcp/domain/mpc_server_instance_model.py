from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column


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
    status: Mapped[str] = mapped_column(String(50), default="pending")

    def __init__(
        self,
        name: str,
        description: str | None = None,
        server_spec_id: str | None = None,
        json_spec: dict[str, Any] | None = None,
        status: str = "pending",
        workspace_id: str | None = None,
        created_by: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = name
        self.description = description
        self.server_spec_id = server_spec_id
        self.json_spec = json_spec or {}
        self.status = status
        if workspace_id is not None:
            self.workspace_id = workspace_id
        if created_by is not None:
            self.created_by = created_by

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
