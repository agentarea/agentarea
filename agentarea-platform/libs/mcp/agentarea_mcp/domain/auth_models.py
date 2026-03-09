"""Domain models for MCP authentication, OAuth links, and compound structures."""

from datetime import datetime
from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

# ---------------------------------------------------------------------------
# Auth type constants
# ---------------------------------------------------------------------------
AUTH_TYPE_API_KEY = "api_key"
AUTH_TYPE_BEARER = "bearer"
AUTH_TYPE_OAUTH2 = "oauth2"
VALID_AUTH_TYPES = {AUTH_TYPE_API_KEY, AUTH_TYPE_BEARER, AUTH_TYPE_OAUTH2}

# Routing mode constants for compound MCPs
ROUTING_MODE_PARALLEL = "parallel"
ROUTING_MODE_FALLBACK = "fallback"
ROUTING_MODE_CONDITIONAL = "conditional"
VALID_ROUTING_MODES = {ROUTING_MODE_PARALLEL, ROUTING_MODE_FALLBACK, ROUTING_MODE_CONDITIONAL}

# Access control constants for OAuth links
ACCESS_CONTROL_WORKSPACE = "workspace"
ACCESS_CONTROL_PUBLIC = "public"
VALID_ACCESS_CONTROLS = {ACCESS_CONTROL_WORKSPACE, ACCESS_CONTROL_PUBLIC}


class MCPAuthConfig(BaseModel, WorkspaceScopedMixin):
    """Authentication configuration for MCP server connections.

    Stores non-sensitive config fields directly; sensitive credentials
    are kept in the secret manager under ``secret_key``.
    """

    __tablename__ = "mcp_auth_configs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # auth_type: api_key | bearer | oauth2
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Non-sensitive config (e.g. header_name, token_url, client_id, scopes)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Key under which encrypted credentials are stored in the secret manager
    secret_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    def __init__(
        self,
        name: str,
        auth_type: str,
        config: dict[str, Any] | None = None,
        description: str | None = None,
        secret_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        if auth_type not in VALID_AUTH_TYPES:
            raise ValueError(f"Invalid auth_type '{auth_type}'. Must be one of {VALID_AUTH_TYPES}")
        super().__init__(**kwargs)
        self.name = name
        self.auth_type = auth_type
        self.config = config or {}
        self.description = description
        self.secret_key = secret_key

    def validate_config(self) -> None:
        """Raise ValueError if required fields for the auth type are missing."""
        if self.auth_type == AUTH_TYPE_API_KEY:
            if not self.config.get("header_name"):
                raise ValueError("api_key auth requires 'header_name' in config")
        elif self.auth_type == AUTH_TYPE_OAUTH2:
            for field in ("client_id", "token_url"):
                if not self.config.get(field):
                    raise ValueError(f"oauth2 auth requires '{field}' in config")


class CompoundMCP(BaseModel, WorkspaceScopedMixin):
    """A virtual MCP that proxies requests to multiple underlying MCP instances."""

    __tablename__ = "compound_mcps"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # routing_mode: parallel | fallback | conditional
    routing_mode: Mapped[str] = mapped_column(
        String(50), nullable=False, default=ROUTING_MODE_PARALLEL
    )

    def __init__(
        self,
        name: str,
        routing_mode: str = ROUTING_MODE_PARALLEL,
        description: str | None = None,
        **kwargs: Any,
    ) -> None:
        if routing_mode not in VALID_ROUTING_MODES:
            raise ValueError(
                f"Invalid routing_mode '{routing_mode}'. Must be one of {VALID_ROUTING_MODES}"
            )
        super().__init__(**kwargs)
        self.name = name
        self.routing_mode = routing_mode
        self.description = description


class CompoundMCPMember(BaseModel):
    """Association between a CompoundMCP and its member MCPServerInstances.

    Uses composite primary key (compound_id, mcp_instance_id) instead of
    the default ``id`` column from BaseModel.
    """

    __tablename__ = "compound_mcp_members"

    # Override BaseModel's id — this table uses a composite PK instead
    id = None  # type: ignore[assignment]
    # Override updated_at — not in the migration
    updated_at = None  # type: ignore[assignment]

    compound_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("compound_mcps.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    mcp_instance_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_server_instances.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Per-member config: namespace_prefix, aliases, condition_expression
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __init__(
        self,
        compound_id: Any,
        mcp_instance_id: Any,
        order: int = 0,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.compound_id = compound_id
        self.mcp_instance_id = mcp_instance_id
        self.order = order
        self.config = config or {}

    def __repr__(self) -> str:
        return f"<CompoundMCPMember compound={self.compound_id} instance={self.mcp_instance_id}>"


class MCPOAuthLink(BaseModel, WorkspaceScopedMixin):
    """An OAuth-protected shareable link for a container-based MCP instance."""

    __tablename__ = "mcp_oauth_links"

    mcp_instance_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_server_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Unique random token embedded in the shareable URL path
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # access_control: workspace | public
    access_control: Mapped[str] = mapped_column(
        String(50), nullable=False, default=ACCESS_CONTROL_WORKSPACE
    )
    # Non-sensitive OAuth provider config (provider, client_id, auth_url, token_url, scopes)
    provider_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __init__(
        self,
        mcp_instance_id: Any,
        token: str,
        access_control: str = ACCESS_CONTROL_WORKSPACE,
        provider_config: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        **kwargs: Any,
    ) -> None:
        if access_control not in VALID_ACCESS_CONTROLS:
            raise ValueError(
                f"Invalid access_control '{access_control}'. Must be one of {VALID_ACCESS_CONTROLS}"
            )
        super().__init__(**kwargs)
        self.mcp_instance_id = mcp_instance_id
        self.token = token
        self.access_control = access_control
        self.provider_config = provider_config or {}
        self.is_active = True
        self.expires_at = expires_at
        self.access_count = 0
        self.last_accessed_at = None


class MCPAccessToken(BaseModel, WorkspaceScopedMixin):
    """Personal Access Token for Bearer-authenticated MCP proxy access.

    The raw token is shown once at creation and never stored — only its
    SHA-256 hash is persisted.  Cursor/Claude configure the token as:
        Authorization: Bearer <raw_token>

    Access is workspace-scoped: the token grants access to any MCP instance
    that belongs to the same workspace.
    """

    __tablename__ = "mcp_access_tokens"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # SHA-256 hex digest of the raw token
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # First 12 chars of the raw token for display (e.g. "aat_AbCdEfGh")
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __init__(
        self,
        name: str,
        token_hash: str,
        token_prefix: str,
        expires_at: datetime | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self.token_hash = token_hash
        self.token_prefix = token_prefix
        self.is_active = True
        self.expires_at = expires_at
        self.access_count = 0
        self.last_accessed_at = None

    def is_expired(self) -> bool:
        return bool(self.expires_at and datetime.utcnow() >= self.expires_at)


class MCPOAuthSession(BaseModel):
    """An authenticated OAuth session for accessing an MCP via an OAuth link."""

    __tablename__ = "mcp_oauth_sessions"

    link_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_oauth_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Opaque token issued as session cookie
    session_token: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    # Identity claims from the OAuth provider (sub, email, name, etc.)
    identity: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __init__(
        self,
        link_id: Any,
        session_token: str,
        expires_at: datetime,
        identity: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.link_id = link_id
        self.session_token = session_token
        self.expires_at = expires_at
        self.identity = identity or {}

    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at
