from enum import StrEnum


class MCPTransport(StrEnum):
    """How a connection is reached: the instance's ``transport`` column, set once at creation."""

    URL = "url"
    DOCKER = "docker"
    COMMAND = "command"
    BUNDLE = "bundle"


#: Transports whose workload the MCP manager runs, starts on demand and reaps.
CONTAINER_TRANSPORTS = frozenset({MCPTransport.DOCKER, MCPTransport.COMMAND})
