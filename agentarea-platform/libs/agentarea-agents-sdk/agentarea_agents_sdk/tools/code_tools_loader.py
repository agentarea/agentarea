"""Loader for code tools configuration from YAML."""

import importlib
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def load_code_tools_config() -> dict[str, Any]:
    """Load code tools configuration from YAML file.

    Returns:
        Dict containing code tools configuration
    """
    # Load config from package-level config directory
    config_path = Path(__file__).parent.parent / "config" / "code_tools.yaml"

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        logger.info(f"Loaded code tools config with {len(config.get('code_tools', {}))} tools")
        return config

    except Exception as e:
        logger.error(f"Failed to load code tools config: {e}")
        # Return minimal config with just calculator
        return {
            "code_tools": {
                "agentarea/calculator": {
                    "display_name": "Calculator",
                    "description": (
                        "Perform basic mathematical calculations like addition, "
                        "subtraction, multiplication, division"
                    ),
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


def get_code_tools_metadata() -> dict[str, dict[str, Any]]:
    """Get metadata for all code tools.

    Returns:
        Dict mapping tool names (publisher/name format) to their metadata
    """
    config = load_code_tools_config()
    return config.get("code_tools", {})


def get_code_tool_class(tool_name: str):
    """Dynamically load a code tool class by name.

    Args:
        tool_name: Name of the tool to load (publisher/name format, e.g., "agentarea/calculator")

    Returns:
        Tool class or None if not found
    """
    metadata = get_code_tools_metadata()

    if tool_name not in metadata:
        logger.error(f"Tool {tool_name} not found in code tools config")
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


def create_code_tool_instance(tool_name: str, toolset_config: dict = None):
    """Create an instance of a code tool with optional toolset configuration.

    Args:
        tool_name: Name of the tool to create (publisher/name format, e.g., "agentarea/calculator")
        toolset_config: Optional configuration for toolsets (which methods to enable)

    Returns:
        Tool instance or None if creation fails
    """
    tool_class = get_code_tool_class(tool_name)

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
