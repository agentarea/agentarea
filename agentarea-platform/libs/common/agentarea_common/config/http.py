"""Outbound HTTP policy: where member-set URLs may point, and which CAs to trust."""

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class HttpSettings(BaseAppSettings):
    """Where URLs that members configure may point, and how their TLS is checked.

    Applies to every path that dials one: LLM provider endpoints, URL MCP
    servers, OpenAPI connections, OAuth discovery, A2A delegates, skill and spec
    imports. Both address settings default to closed.
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
    # Path to a PEM file of CA certificates to trust on outbound TLS in addition
    # to the public roots, for hosts whose chain public bundles leave out (the
    # Russian Trusted Root CA, a corporate CA). Empty: public roots only. A path
    # that cannot be loaded stops the process at startup.
    EXTRA_CA_CERTS: str = ""
