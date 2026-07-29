"""Decorator-driven code tools loader.

Every ``@toolset(namespace=...)``-decorated class self-registers in
``_TOOLSET_REGISTRY`` at import time. This module exposes
``get_code_tools_metadata``, ``get_code_tool_class`` and
``create_code_tool_instance`` to the agent runtime, import/export, and MCP
registry, reading from the live registry. The class IS the source of truth.
"""

from __future__ import annotations

import logging
from typing import Any

from .tool_definition import ToolsetMetadata, get_toolset_registry

logger = logging.getLogger(__name__)


def _ensure_all_toolsets_imported() -> None:
    """Eager-import every module that defines a ``@toolset(...)`` class so the
    registry is populated before lookup. Failures are logged but not fatal —
    a missing optional dependency (e.g. ``agentarea_api.*`` in a worker-only
    install) should not crash the loader.
    """
    # Agent-runtime SDK code tools (math, file, web).
    sdk_modules = [
        "agentarea_agents_sdk.tools.math_toolset",
        "agentarea_agents_sdk.tools.file_toolset",
        "agentarea_agents_sdk.tools.workspace_files_toolset",
        "agentarea_agents_sdk.tools.context_toolset",
        "agentarea_agents_sdk.tools.web_toolset",
        "agentarea_agents_sdk.tools.shell_toolset",
    ]
    # Platform toolsets exposed both to agents (via this loader) and to MCP
    # clients (via apps/api ``get_platform_tools``).
    platform_modules = [
        "agentarea_api.tools.agents_toolset",
        "agentarea_api.tools.runs_toolset",
        # skills_toolset lives in agentarea_agents (a worker-importable lib) so
        # agents running in the worker can register agentarea/skills; the other
        # platform toolsets remain API-only until similarly relocated.
        "agentarea_agents.tools.skills_toolset",
        "agentarea_api.tools.projects_toolset",
        "agentarea_api.tools.openapi_connections_toolset",
        "agentarea_api.tools.mcp_servers_toolset",
        "agentarea_api.tools.providers_toolset",
        "agentarea_api.tools.models_toolset",
        "agentarea_api.tools.secrets_toolset",
        "agentarea_api.tools.audit_toolset",
        "agentarea_api.tools.network_toolset",
        "agentarea_api.tools.workspace_config_toolset",
        "agentarea_api.tools.inbox_toolset",
        "agentarea_api.tools.files_toolset",
    ]
    # Cross-package toolsets that don't live under apps/api but still register.
    extension_modules = [
        "agentarea_triggers.agent_tool",
    ]

    import importlib

    for mod_name in sdk_modules + platform_modules + extension_modules:
        try:
            importlib.import_module(mod_name)
        except Exception as exc:
            logger.debug("Skipping toolset module %s: %s", mod_name, exc)


def _meta_to_dict(meta: ToolsetMetadata, cls: type) -> dict[str, Any]:
    return {
        "namespace": meta.namespace,
        "display_name": meta.display_name,
        "description": meta.description,
        "category": meta.category,
        "enabled_by_default": meta.enabled_by_default,
        "requires_user_confirmation": meta.requires_user_confirmation,
        "class_path": f"{cls.__module__}.{cls.__name__}",
    }


def get_code_tools_metadata() -> dict[str, dict[str, Any]]:
    """Return metadata for every registered toolset, keyed by namespace.

    Mirrors the old YAML shape (``name -> {display_name, description, ...}``)
    so existing consumers (import/export, MCP registry) keep working.
    """
    _ensure_all_toolsets_imported()
    registry = get_toolset_registry()
    return {ns: _meta_to_dict(cls.__toolset_meta__, cls) for ns, cls in registry.items()}


def get_code_tool_class(tool_name: str):
    """Look up a registered Toolset class by its ``namespace``.

    Returns ``None`` if not found, so callers can log+skip rather than crash.
    """
    _ensure_all_toolsets_imported()
    registry = get_toolset_registry()
    cls = registry.get(tool_name)
    if cls is None:
        logger.error("Toolset %s not found in registry", tool_name)
    return cls


def create_code_tool_instance(
    tool_name: str,
    toolset_config: dict | None = None,
    extra_kwargs: dict | None = None,
):
    """Instantiate a registered toolset by namespace, merging optional kwargs.

    Args:
        tool_name: Toolset namespace (e.g. ``agentarea/files``).
        toolset_config: Per-method config (e.g. ``disabled_methods``) passed
            to the constructor when the class supports it.
        extra_kwargs: Runtime-injected dependencies (storage client, workspace
            id, default agent id, etc.). Merged on top of ``toolset_config``.

    Returns:
        Instantiated tool, or ``None`` if the class is missing or constructor
        raised.
    """
    cls = get_code_tool_class(tool_name)
    if cls is None:
        return None

    kwargs: dict = {}
    if toolset_config:
        kwargs.update(toolset_config)
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    try:
        if kwargs:
            logger.debug("Creating %s with kwargs: %s", tool_name, list(kwargs))
            return cls(**kwargs)
        logger.debug("Creating %s with default constructor", tool_name)
        return cls()
    except Exception as exc:
        logger.error("Failed to create tool instance %s: %s", tool_name, exc)
        return None
