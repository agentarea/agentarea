"""Re-export shim: the platform-toolset context helpers now live in
``agentarea_agents.tools.platform_base`` so the worker (which cannot import
``agentarea_api``) can use them too. Kept here so the API-side toolsets and
``client_mcp`` keep importing ``from .base import ...`` unchanged.
"""

from agentarea_agents.tools.platform_base import (
    platform_context,
    platform_read_context,
)

__all__ = ["platform_context", "platform_read_context"]
