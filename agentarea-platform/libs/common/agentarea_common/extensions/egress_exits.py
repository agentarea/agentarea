"""Whether this deployment can route an MCP instance through an egress exit.

Additive extension point (see AGENTS.md → EXTENSION POINTS): an installed
``egress_exits`` extension is active by being installed. Core keeps the exits
table and its API; the proxy and the dataplane hook that enforce a binding are
the enterprise edition's. Without the extension the API answers 404 and no
instance may bind an exit, because nothing would route it.
"""

from .registry import ExtensionRegistry

EGRESS_EXITS_EXTENSION = "egress_exits"


class EgressExitsNotSupportedError(LookupError):
    """This deployment has no egress exits."""

    def __init__(self) -> None:
        super().__init__("egress exits need the enterprise edition")


def egress_exits_supported() -> bool:
    if ExtensionRegistry.has(EGRESS_EXITS_EXTENSION):
        return True
    failure = ExtensionRegistry.get_failure(EGRESS_EXITS_EXTENSION)
    if failure is not None:
        raise RuntimeError(f"egress_exits extension is installed but failed to load: {failure}")
    return False


def require_egress_exits() -> None:
    if not egress_exits_supported():
        raise EgressExitsNotSupportedError()
