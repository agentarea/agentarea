"""Tests for CORS configuration on AppSettings."""

from agentarea_common.config.app import AppSettings


def test_cors_allowed_origins_defaults_to_any_origin():
    settings = AppSettings()
    assert settings.cors_allowed_origins == ["*"]


def test_cors_allowed_origins_parses_comma_separated_list():
    settings = AppSettings(
        CORS_ORIGINS="https://app.agentarea.dev, https://admin.agentarea.dev"
    )
    assert settings.cors_allowed_origins == [
        "https://app.agentarea.dev",
        "https://admin.agentarea.dev",
    ]


def test_cors_allowed_origins_strips_and_drops_blanks():
    settings = AppSettings(CORS_ORIGINS=" https://a.dev ,, https://b.dev , ")
    assert settings.cors_allowed_origins == ["https://a.dev", "https://b.dev"]


def test_cors_origin_regex_defaults_to_none():
    # Static-list-only deployments leave the regex unset.
    settings = AppSettings()
    assert settings.CORS_ORIGIN_REGEX is None


def test_cors_origin_regex_preserved_when_set():
    settings = AppSettings(
        CORS_ORIGIN_REGEX=r"https://.*\.agentarea\.dev"
    )
    assert settings.CORS_ORIGIN_REGEX == r"https://.*\.agentarea\.dev"


def test_cors_methods_and_headers_default_to_wildcard():
    settings = AppSettings()
    assert settings.cors_allowed_methods == ["*"]
    assert settings.cors_allowed_headers == ["*"]


def test_cors_methods_and_headers_parse_comma_separated():
    settings = AppSettings(
        CORS_METHODS="GET, POST ,DELETE",
        CORS_HEADERS="Authorization, Content-Type",
    )
    assert settings.cors_allowed_methods == ["GET", "POST", "DELETE"]
    assert settings.cors_allowed_headers == ["Authorization", "Content-Type"]


def test_cors_max_age_default_and_overridable():
    assert AppSettings().CORS_MAX_AGE == 3600
    assert AppSettings(CORS_MAX_AGE=600).CORS_MAX_AGE == 600
