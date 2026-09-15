"""PLATFORM_PROVIDERS must not be able to stop the process from starting.

Settings are constructed during import, before logging is usable and before any
handler could report the problem. A ValidationError there is not a misconfigured
feature — it is a pod that crash-loops, for every tenant, including all the ones
bringing their own keys who are not using this feature at all.

The value arrives from Helm, so "" is not an exotic input: a value left empty
renders as "", and that is how the feature's own disabled state is spelled in the
production values file.
"""

import pytest
from agentarea_common.config.app import AppSettings
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def _no_ambient_value(monkeypatch):
    monkeypatch.delenv("PLATFORM_PROVIDERS", raising=False)


def test_unset_means_no_platform_providers():
    """The open build's default: supplies no keys, offers no keyless models."""
    assert AppSettings().PLATFORM_PROVIDERS is None


@pytest.mark.parametrize("blank", ["", "   ", "\n", "\t "], ids=repr)
def test_blank_is_disabled_not_a_crash(monkeypatch, blank):
    """pydantic-settings JSON-decodes this field, and "" is not JSON."""
    monkeypatch.setenv("PLATFORM_PROVIDERS", blank)
    assert AppSettings().PLATFORM_PROVIDERS is None


def test_empty_json_list_is_also_disabled(monkeypatch):
    monkeypatch.setenv("PLATFORM_PROVIDERS", "[]")
    assert AppSettings().PLATFORM_PROVIDERS == []


def test_a_declaration_is_parsed(monkeypatch):
    monkeypatch.setenv(
        "PLATFORM_PROVIDERS",
        '[{"provider_key":"openai","credential":"openai",'
        '"models":[{"model_name":"gpt-4o-mini","context_window":128000,'
        '"input_cost_per_token":1.5e-7,"output_cost_per_token":6e-7}]}]',
    )
    providers = AppSettings().PLATFORM_PROVIDERS
    assert providers is not None
    assert providers[0]["provider_key"] == "openai"


def test_malformed_json_still_fails_loudly(monkeypatch):
    """Blank is tolerated; wrong is not.

    An operator who wrote a declaration and got the syntax wrong intended to offer
    models. Starting anyway would silently offer none, which looks identical to the
    feature not working — so this one keeps the crash.
    """
    monkeypatch.setenv("PLATFORM_PROVIDERS", "{not json")
    with pytest.raises(ValidationError):
        AppSettings()
