"""Loader for builtin tools configuration from YAML."""

import importlib
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def load_builtin_tools_config() -> dict[str, Any]:
    """Load builtin tools configuration from YAML file.

    Returns:
        Dict containing builtin tools configuration
    """
    # Move config to package-level config directory (not in tools/)
    config_path = Path(__file__).parent.parent / "config" / "builtin_tools.yaml"

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        logger.info(
            f"Loaded builtin tools config with {len(config.get('builtin_tools', {}))} tools"
        )
        return config

    except Exception as e:
        logger.error(f"Failed to load builtin tools config: {e}")
        # Return minimal config with just calculator
        return {
            "builtin_tools": {
                "calculator": {
                    "name": "calculator",
                    "display_name": "Calculator",
                    "description": "Perform basic mathematical calculations like addition, subtraction, multiplication, division",
                    "class_path": "agentarea_agents_sdk.tools.calculate_tool.CalculateTool",
                    "category": "utility",
                    "enabled_by_default": False,
                    "requires_user_confirmation": False,
                }
            },
            "categories": [
                {"id": "utility", "name": "Utility Tools", "description": "Basic utility functions"}
            ],
        }


def get_builtin_tools_metadata() -> dict[str, dict[str, Any]]:
    """Get metadata for all builtin tools.

    Returns:
        Dict mapping tool names to their metadata
    """
    config = load_builtin_tools_config()
    return config.get("builtin_tools", {})


def get_builtin_tool_class(tool_name: str):
    """Dynamically load a builtin tool class by name.

    Args:
        tool_name: Name of the tool to load

    Returns:
        Tool class or None if not found
    """
    metadata = get_builtin_tools_metadata()

    if tool_name not in metadata:
        logger.error(f"Tool {tool_name} not found in builtin tools config")
        return None

    tool_info = metadata[tool_name]
    class_path = tool_info.get("class_path")

    if not class_path:
        logger.error(f"No class_path specified for tool {tool_name}")
        return None

    try:
        module_name, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        tool_class = getattr(module, class_name)
        return tool_class

    except Exception as e:
        logger.error(f"Failed to load tool class {class_path}: {e}")
        return None


def create_builtin_tool_instance(tool_name: str, toolset_config: dict = None):
    """Create an instance of a builtin tool with optional toolset configuration.

    Args:
        tool_name: Name of the tool to create
        toolset_config: Optional configuration for toolsets (which methods to enable)

    Returns:
        Tool instance or None if creation fails
    """
    tool_class = get_builtin_tool_class(tool_name)

    if not tool_class:
        return None

    try:
        if toolset_config:
            # This is a toolset - create with specific method configuration
            logger.debug(f"Creating toolset {tool_name} with config: {toolset_config}")
            tool_instance = tool_class(**toolset_config)
        else:
            # This is a regular tool - create with default constructor
            logger.debug(f"Creating regular tool {tool_name}")
            tool_instance = tool_class()

        return tool_instance

    except Exception as e:
        logger.error(f"Failed to create tool instance {tool_name}: {e}")
        return None
