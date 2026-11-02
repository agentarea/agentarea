"""What a connection authorizes against, and which OAuth client it uses for that."""

from types import SimpleNamespace

import pytest
from agentarea_common.config.mcp import MCPSettings
from agentarea_mcp.application import platform_oauth_app
from agentarea_mcp.application.oauth_profile import (
    OAuthProfile,
    auto_credential_source,
    platform_app_for,
)

_GITHUB_APP = {
    "issuer": "https://github.com/login/oauth",
    "client_id": "Iv1.platform",
    "client_secret": "platform-secret",  # pragma: allowlist secret
    "authorization_endpoint": "https://github.com/login/oauth/authorize",
    "token_endpoint": "https://github.com/login/oauth/access_token",
    "resource_origins": ["https://api.githubcopilot.com"],
}

_YANDEX_APP = {
    "issuer": "https://oauth.yandex.ru",
    "client_id": "yandex-client",
    "client_secret": "yandex-secret",  # pragma: allowlist secret
    "authorization_endpoint": "https://oauth.yandex.ru/authorize",
    "token_endpoint": "https://oauth.yandex.ru/token",
    "resource_origins": ["https://api-metrika.yandex.net", "https://api.direct.yandex.com"],
}


@pytest.fixture
def platform_apps(monkeypatch):
    configured: list[dict] = []
    monkeypatch.setattr(
        platform_oauth_app,
        "get_settings",
        lambda: SimpleNamespace(mcp=MCPSettings(OAUTH_APPS=configured)),
    )
    return configured


def _discovered(**overrides) -> OAuthProfile:
    """A profile MCP discovery produced: the issuer is known, the endpoints are the server's."""
    return OAuthProfile(
        **{
            "provider": "mcp-remote",
            "issuer": "https://github.com/login/oauth",
            "authorization_endpoint": "https://github.com/login/oauth/authorize",
            "token_endpoint": "https://token-thief.example/token",
            "resource_origins": ("https://api.githubcopilot.com",),
            **overrides,
        }
    )


def _template(**overrides) -> OAuthProfile:
    """A profile a trusted catalog template declared: endpoints, no issuer."""
    return OAuthProfile(
        **{
            "provider": "yandex-metrica",
            "authorization_endpoint": "https://oauth.yandex.ru/authorize",
            "token_endpoint": "https://oauth.yandex.ru/token",
            "resource_origins": ("https://api-metrika.yandex.net",),
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("profile", "found"),
    [
        (_discovered(), True),
        (_discovered(issuer="https://github.com/login-oauth"), False),
        (_discovered(resource_origins=("https://api.githubcopilot.com.evil.example",)), False),
        (_template(), True),
        (_template(token_endpoint="https://oauth.example.test/token"), False),
        (_template(authorization_endpoint="https://oauth.example.test/authorize"), False),
        (
            _template(
                resource_origins=("https://api-metrika.yandex.net", "https://evil.example"),
            ),
            False,
        ),
    ],
    ids=[
        "issuer-and-origin",
        "other-issuer",
        "other-origin",
        "template-endpoints",
        "template-token-endpoint-differs",
        "template-authorize-endpoint-differs",
        "template-sends-tokens-elsewhere-too",
    ],
)
def test_the_platform_app_serves_a_profile_only_when_it_matches(platform_apps, profile, found):
    platform_apps.extend([_GITHUB_APP, _YANDEX_APP])

    assert (platform_app_for(profile) is not None) is found


def test_nothing_configured_means_no_platform_app(platform_apps):
    assert platform_app_for(_discovered()) is None
    assert platform_app_for(_template()) is None


def test_a_platform_app_wins_over_dynamic_registration(platform_apps):
    platform_apps.append(_GITHUB_APP)

    profile = _discovered(registration_endpoint="https://github.com/register")

    assert auto_credential_source(profile) == "platform"


def test_dynamic_registration_is_used_when_no_platform_app_serves_the_profile(platform_apps):
    profile = _discovered(registration_endpoint="https://as.example/register")

    assert auto_credential_source(profile) == "dynamic"


def test_without_either_the_workspace_brings_its_own_app(platform_apps):
    assert auto_credential_source(_discovered()) is None
    assert auto_credential_source(_template()) is None


def test_a_platform_app_replaces_the_discovered_endpoints(platform_apps):
    platform_apps.append(_GITHUB_APP)
    profile = _discovered()

    served = profile.served_by(platform_app_for(profile))

    assert served.token_endpoint == "https://github.com/login/oauth/access_token"  # noqa: S105
    assert served.authorization_endpoint == "https://github.com/login/oauth/authorize"
    assert served.issuer == "https://github.com/login/oauth"


_OFFERED = ("gmail.readonly", "gmail.modify", "mail.google.com")


def test_without_a_choice_the_declared_default_scopes_are_requested():
    profile = _discovered(scopes=_OFFERED, default_scopes=("gmail.modify",))

    assert profile.requested_scopes(None) == ("gmail.modify",)


def test_without_a_default_every_offered_scope_is_requested():
    assert _discovered(scopes=_OFFERED).requested_scopes(None) == _OFFERED


def test_a_choice_narrows_the_request_to_what_was_picked():
    profile = _discovered(scopes=_OFFERED, default_scopes=("gmail.modify",))

    assert profile.requested_scopes(["mail.google.com", "gmail.readonly", "gmail.readonly"]) == (
        "mail.google.com",
        "gmail.readonly",
    )


@pytest.mark.parametrize(
    "chosen",
    [[], ["gmail.send"], ["gmail.readonly", "gmail.send"]],
    ids=["nothing", "not-offered", "partly-not-offered"],
)
def test_a_choice_outside_the_offered_scopes_is_refused(chosen):
    with pytest.raises(ValueError):
        _discovered(scopes=_OFFERED).requested_scopes(chosen)


def test_nothing_can_be_picked_when_the_server_offers_nothing():
    profile = _discovered()

    assert profile.requested_scopes(None) == ()
    with pytest.raises(ValueError):
        profile.requested_scopes(["repo"])


def test_a_default_the_server_does_not_offer_is_refused():
    with pytest.raises(ValueError, match="gmail.send"):
        _discovered(scopes=_OFFERED, default_scopes=("gmail.modify", "gmail.send"))


def test_the_platform_app_keeps_the_default_scopes(platform_apps):
    platform_apps.append(_GITHUB_APP)
    profile = _discovered(scopes=("repo", "read:org"), default_scopes=("read:org",))

    served = profile.served_by(platform_app_for(profile))

    assert served.requested_scopes(None) == ("read:org",)
