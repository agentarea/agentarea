"""Canonical format validation tests."""

import pytest
from agentarea_bundles.schemas.bundle import (
    Bundle,
    SetupField,
    SetupFieldType,
    resolve_placeholders,
    setup_refs,
)
from pydantic import ValidationError


def test_minimal_package_valid():
    pkg = Bundle(name="p")
    assert pkg.schema_version == "0.1.0"
    assert pkg.mcps == []


def test_unsupported_schema_version_rejected():
    with pytest.raises(ValidationError):
        Bundle(name="p", schema_version="9.9.9")


def test_extra_keys_forbidden():
    with pytest.raises(ValidationError):
        Bundle.model_validate({"name": "p", "unknown": 1})


def test_select_field_requires_options():
    with pytest.raises(ValidationError):
        SetupField(key="r", label="Region", type=SetupFieldType.SELECT)


def test_invalid_key_rejected():
    with pytest.raises(ValidationError):
        SetupField(key="9bad", label="x")


def test_skill_content_required_for_content_source():
    with pytest.raises(ValidationError):
        Bundle.model_validate(
            {"name": "p", "skills": [{"key": "s", "name": "S", "source_type": "content"}]}
        )


def test_setup_refs_extraction():
    assert setup_refs("Bearer ${setup.github_token}") == ["github_token"]
    assert setup_refs("no refs") == []
    assert setup_refs(123) == []


def test_resolve_placeholders_substitutes_and_keeps_missing():
    assert resolve_placeholders("${setup.a}/${setup.b}", {"a": "1"}) == "1/${setup.b}"
