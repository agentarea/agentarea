"""Unit tests for provider icon URL resolution."""

import pytest
from agentarea_api.api.v1._provider_icons import build_provider_icon_url


def test_none_icon_returns_none():
    assert build_provider_icon_url(None) is None
    assert build_provider_icon_url("") is None


def test_bare_id_resolves_against_api_base_url(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "https://api.agentarea.ai")
    # AppSettings is lru_cached; clear so the env override takes effect.
    from agentarea_common.config.app import get_app_settings

    get_app_settings.cache_clear()

    assert (
        build_provider_icon_url("openai")
        == "https://api.agentarea.ai/static/icons/providers/openai.svg"
    )


def test_trailing_slash_on_base_is_normalized(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "https://api.agentarea.ai/")
    from agentarea_common.config.app import get_app_settings

    get_app_settings.cache_clear()

    assert (
        build_provider_icon_url("anthropic")
        == "https://api.agentarea.ai/static/icons/providers/anthropic.svg"
    )


@pytest.mark.parametrize(
    "full",
    [
        "https://cdn.example.com/icons/foo.svg",
        "http://cdn.example.com/icons/foo.png",
    ],
)
def test_full_url_passes_through(full):
    # Remote registry entries supply their own absolute icon URL; never rewrite
    # them, and never depend on request host or API_BASE_URL for these.
    assert build_provider_icon_url(full) == full


def test_root_relative_path_is_not_passed_through(monkeypatch):
    # A root-relative path would resolve against the *frontend* origin in the
    # browser (the host that 404/500s), so it must NOT pass through. It is
    # treated as an id and pinned to the API base instead.
    monkeypatch.setenv("API_BASE_URL", "https://api.agentarea.ai")
    from agentarea_common.config.app import get_app_settings

    get_app_settings.cache_clear()

    result = build_provider_icon_url("/static/icons/providers/custom.svg")
    assert result.startswith("https://api.agentarea.ai/static/icons/providers/")
    assert not result.startswith("/")
