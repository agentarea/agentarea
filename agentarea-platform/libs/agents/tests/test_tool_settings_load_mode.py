"""ToolSettingsYAML.load_mode field — accepts the two literals, round-trips through YAML."""

import yaml
from pydantic import ValidationError
import pytest

from agentarea_agents.schemas.import_export import (
    ToolConfigYAML,
    ToolSettingsYAML,
)


def test_load_mode_defaults_to_none():
    s = ToolSettingsYAML()
    assert s.load_mode is None


def test_load_mode_accepts_explicit():
    s = ToolSettingsYAML(load_mode="explicit")
    assert s.load_mode == "explicit"


def test_load_mode_accepts_searchable():
    s = ToolSettingsYAML(load_mode="searchable")
    assert s.load_mode == "searchable"


def test_load_mode_rejects_unknown_string():
    with pytest.raises(ValidationError):
        ToolSettingsYAML(load_mode="lazy")  # type: ignore[arg-type]


def test_load_mode_round_trips_through_yaml():
    original = ToolConfigYAML(
        type="openapi",
        name="stripe-api",
        settings=ToolSettingsYAML(
            openapi_connection_id="11111111-1111-1111-1111-111111111111",
            load_mode="searchable",
        ),
    )
    serialized = yaml.safe_dump(original.model_dump(exclude_none=True))
    parsed = ToolConfigYAML(**yaml.safe_load(serialized))
    assert parsed.settings is not None
    assert parsed.settings.load_mode == "searchable"
    assert parsed.settings.openapi_connection_id == "11111111-1111-1111-1111-111111111111"


def test_load_mode_omitted_when_none_in_export():
    """exclude_none=True keeps existing YAML files free of the new field."""
    cfg = ToolConfigYAML(
        type="openapi",
        name="stripe-api",
        settings=ToolSettingsYAML(openapi_connection_id="abc"),
    )
    dumped = cfg.model_dump(exclude_none=True)
    assert "load_mode" not in dumped["settings"]


def test_load_mode_legal_on_non_openapi_tools_for_now():
    """Field is parsed regardless of type — validation that it only applies to
    openapi happens at runtime in the workflow, not in the schema."""
    cfg = ToolConfigYAML(
        type="mcp",
        name="some-mcp",
        settings=ToolSettingsYAML(load_mode="searchable"),
    )
    assert cfg.settings is not None
    assert cfg.settings.load_mode == "searchable"
