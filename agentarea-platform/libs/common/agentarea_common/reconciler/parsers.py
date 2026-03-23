"""YAML parsing and validation for seed data files."""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class YAMLValidationError(Exception):
    """Raised when YAML content fails validation."""

    pass


# Required fields per entity type
REQUIRED_FIELDS: dict[str, list[str]] = {
    "mcp_servers": ["name"],
    "agents": ["name"],
    "skills": ["name"],
    "models": [],  # models has nested structure
}


def parse_yaml(file: Path, entity_type: str) -> list[dict[str, Any]]:
    """Parse and validate a YAML seed data file.

    Args:
        file: Path to YAML file.
        entity_type: One of mcp_servers, agents, skills, models.

    Returns:
        List of entity dicts.

    Raises:
        YAMLValidationError: If YAML is invalid or missing required fields.
    """
    try:
        with open(file) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise YAMLValidationError(f"Invalid YAML in {file}: {e}") from e

    if not isinstance(data, dict):
        raise YAMLValidationError(f"Expected dict at top level in {file}, got {type(data)}")

    entities = data.get(entity_type, [])
    if not isinstance(entities, list):
        raise YAMLValidationError(f"Expected list for '{entity_type}' in {file}")

    required = REQUIRED_FIELDS.get(entity_type, [])
    for i, entity in enumerate(entities):
        if not isinstance(entity, dict):
            raise YAMLValidationError(f"Entity {i} in {file} is not a dict")
        for field in required:
            if field not in entity:
                raise YAMLValidationError(f"Entity {i} in {file} missing required field: {field}")

    return entities
