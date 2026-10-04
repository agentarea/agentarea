"""Outbound HTTP policy: which private addresses member-set URLs may reach."""

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class HttpSettings(BaseAppSettings):
    """Where URLs that members configure may point.

    Applies to every path that dials one: LLM provider endpoints, URL MCP
    servers, OpenAPI connections, OAuth discovery, A2A delegates, skill and spec
    imports. Both default to closed.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_HTTP_")

    # Comma-separated host globs and CIDRs that member-supplied URLs (MCP
    # servers, OAuth discovery, model endpoints, skill and spec imports) may
    # reach even though they are private or loopback, e.g. "localhost" for a
    # local Ollama in development. Empty: only public addresses. Name each
    # endpoint: "*.svc.cluster.local" or a cluster CIDR opens every in-cluster
    # service to every member.
    PRIVATE_ALLOWLIST: str = ""
    # Admit every private address. Single-tenant installs only.
    ALLOW_PRIVATE: bool = False
