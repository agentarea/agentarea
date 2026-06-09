"""OpenApiToolSettings.load_mode — two literals, YAML round-trip, openapi-only."""

import pytest
import yaml
from agentarea_agents.schemas.import_export import (
    TOOL_CONFIG_ADAPTER,
    CodeToolConfig,
    OpenApiToolConfig,
    OpenApiToolSettings,
)
from pydantic import ValidationError


def test_load_mode_defaults_to_none():
    assert OpenApiToolSettings().load_mode is None


def test_load_mode_accepts_explicit():
    assert OpenApiToolSettings(load_mode="explicit").load_mode == "explicit"


def test_load_mode_accepts_searchable():
    assert OpenApiToolSettings(load_mode="searchable").load_mode == "searchable"


def test_load_mode_rejects_unknown_string():
    with pytest.raises(ValidationError):
        OpenApiToolSettings(load_mode="lazy")  # type: ignore[arg-type]


def test_load_mode_round_trips_through_yaml():
    original = OpenApiToolConfig(
        name="stripe-api",
        settings=OpenApiToolSettings(
            openapi_connection_id="11111111-1111-1111-1111-111111111111",
            load_mode="searchable",
        ),
    )
    serialized = yaml.safe_dump(original.model_dump(exclude_none=True))
    parsed = TOOL_CONFIG_ADAPTER.validate_python(yaml.safe_load(serialized))
    assert isinstance(parsed, OpenApiToolConfig)
    assert parsed.settings is not None
    assert parsed.settings.load_mode == "searchable"
    assert parsed.settings.openapi_connection_id == "11111111-1111-1111-1111-111111111111"


def test_load_mode_omitted_when_none_in_export():
    """exclude_none=True keeps existing YAML files free of the new field."""
    cfg = OpenApiToolConfig(
        name="stripe-api",
        settings=OpenApiToolSettings(openapi_connection_id="abc"),
    )
    dumped = cfg.model_dump(exclude_none=True)
    assert "load_mode" not in dumped["settings"]


def test_load_mode_is_openapi_only():
    """DDD win: load_mode is unrepresentable on non-openapi tools — dropped, not carried."""
    cfg = TOOL_CONFIG_ADAPTER.validate_python(
        {"type": "code", "name": "x", "settings": {"load_mode": "searchable"}}
    )
    assert isinstance(cfg, CodeToolConfig)
    assert cfg.settings is not None
    assert not hasattr(cfg.settings, "load_mode")
