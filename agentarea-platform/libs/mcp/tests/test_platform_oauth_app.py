"""AGENTAREA_MCP_OAUTH_APPS: the operator's MCP OAuth apps and how one is found."""

from types import SimpleNamespace

import pytest
from agentarea_common.config.mcp import MCPSettings
from agentarea_mcp.application import platform_oauth_app
from agentarea_mcp.application.platform_oauth_app import find_platform_oauth_app
from pydantic import ValidationError

_GITHUB_APP = {
    "issuer": "https://github.com/login/oauth",
    "client_id": "Iv1.platform",
    "client_secret": "platform-secret",  # pragma: allowlist secret
    "authorization_endpoint": "https://github.com/login/oauth/authorize",
    "token_endpoint": "https://github.com/login/oauth/access_token",
    "resource_origins": ["https://api.githubcopilot.com"],
}


def test_unset_means_no_platform_apps():
    assert MCPSettings().OAUTH_APPS == ()


def test_apps_are_found_by_issuer():
    settings = MCPSettings(OAUTH_APPS=[_GITHUB_APP])

    app = settings.oauth_app_for("https://github.com/login/oauth/")

    assert app is not None
    assert app.client_id == "Iv1.platform"
    assert settings.oauth_app_for("https://accounts.google.com") is None


def test_the_env_var_is_parsed_as_json(monkeypatch):
    import json

    monkeypatch.setenv("AGENTAREA_MCP_OAUTH_APPS", json.dumps([_GITHUB_APP]))

    assert MCPSettings().OAUTH_APPS[0].resource_origins == ("https://api.githubcopilot.com",)


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_secret": ""},
        {"client_id": ""},
        {"resource_origins": []},
        {"resource_origins": ["https://api.githubcopilot.com/"]},
        {"token_endpoint": "http://github.com/login/oauth/access_token"},
        {"issuer": "https://github.com/login/oauth/"},
        {"unexpected": "field"},
    ],
)
def test_a_malformed_app_fails_loud_without_echoing_the_secret(overrides):
    with pytest.raises(ValidationError) as excinfo:
        MCPSettings(OAUTH_APPS=[{**_GITHUB_APP, **overrides}])

    assert "platform-secret" not in str(excinfo.value)


def test_one_app_per_issuer():
    with pytest.raises(ValidationError, match="twice"):
        MCPSettings(OAUTH_APPS=[_GITHUB_APP, _GITHUB_APP])


@pytest.mark.parametrize(
    ("apps", "mcp_url", "found"),
    [
        ([_GITHUB_APP], "https://api.githubcopilot.com/mcp/", True),
        ([_GITHUB_APP], "https://api.githubcopilot.com.evil.example/mcp/", False),
        (
            [{**_GITHUB_APP, "issuer": "https://github.com/login-oauth"}],
            "https://api.githubcopilot.com/mcp/",
            False,
        ),
        ([], "https://api.githubcopilot.com/mcp/", False),
    ],
    ids=["serves", "other-origin", "other-issuer", "none-configured"],
)
def test_lookup_needs_the_issuer_and_the_mcp_origin_to_match(monkeypatch, apps, mcp_url, found):
    monkeypatch.setattr(
        platform_oauth_app,
        "get_settings",
        lambda: SimpleNamespace(mcp=MCPSettings(OAUTH_APPS=apps)),
    )

    app = find_platform_oauth_app("https://github.com/login/oauth", mcp_url)

    assert (app is not None) is found
