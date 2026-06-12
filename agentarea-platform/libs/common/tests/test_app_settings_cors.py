"""Tests for CORS configuration on AppSettings."""

import pytest
from agentarea_common.config.app import AppSettings


def test_cors_allowed_origins_defaults_to_local_frontend():
    settings = AppSettings()
    assert settings.cors_allowed_origins == ["http://localhost:3000"]


def test_cors_allowed_origins_parses_comma_separated_list():
    settings = AppSettings(
        CORS_ALLOWED_ORIGINS="https://app.agentarea.dev, https://admin.agentarea.dev"
    )
    assert settings.cors_allowed_origins == [
        "https://app.agentarea.dev",
        "https://admin.agentarea.dev",
    ]


def test_cors_allowed_origins_strips_and_drops_blanks():
    settings = AppSettings(CORS_ALLOWED_ORIGINS=" https://a.dev ,, https://b.dev , ")
    assert settings.cors_allowed_origins == ["https://a.dev", "https://b.dev"]


def test_cors_allowed_origins_is_never_wildcard_by_default():
    # The whole point of the fix: default must not be "*" (which, combined with
    # allow_credentials=True, reflects any origin for credentialed requests).
    settings = AppSettings()
    assert "*" not in settings.cors_allowed_origins


def test_cors_origin_regex_defaults_to_none():
    # Static-list-only deployments leave the regex unset.
    settings = AppSettings()
    assert settings.CORS_ALLOWED_ORIGIN_REGEX is None


def test_cors_origin_regex_preserved_when_set():
    settings = AppSettings(
        CORS_ALLOWED_ORIGIN_REGEX=r"https://.*\.agentarea\.dev"
    )
    assert settings.CORS_ALLOWED_ORIGIN_REGEX == r"https://.*\.agentarea\.dev"


def test_cors_methods_and_headers_default_to_wildcard():
    settings = AppSettings()
    assert settings.cors_allowed_methods == ["*"]
    assert settings.cors_allowed_headers == ["*"]


def test_cors_methods_and_headers_parse_comma_separated():
    settings = AppSettings(
        CORS_ALLOWED_METHODS="GET, POST ,DELETE",
        CORS_ALLOWED_HEADERS="Authorization, Content-Type",
    )
    assert settings.cors_allowed_methods == ["GET", "POST", "DELETE"]
    assert settings.cors_allowed_headers == ["Authorization", "Content-Type"]


def test_cors_credentials_and_max_age_overridable():
    settings = AppSettings(CORS_ALLOW_CREDENTIALS=False, CORS_MAX_AGE=600)
    assert settings.CORS_ALLOW_CREDENTIALS is False
    assert settings.CORS_MAX_AGE == 600


def test_cors_credentials_default_true_and_max_age_default():
    settings = AppSettings()
    assert settings.CORS_ALLOW_CREDENTIALS is True
    assert settings.CORS_MAX_AGE == 3600


def test_wildcard_origin_with_credentials_is_rejected():
    # The footgun we just fixed: "*" + credentials reflects any origin for
    # credentialed reads (CSRF). Must fail fast at config load.
    with pytest.raises(ValueError, match="CORS"):
        AppSettings(CORS_ALLOWED_ORIGINS="*", CORS_ALLOW_CREDENTIALS=True)


def test_wildcard_origin_allowed_when_credentials_disabled():
    settings = AppSettings(CORS_ALLOWED_ORIGINS="*", CORS_ALLOW_CREDENTIALS=False)
    assert settings.cors_allowed_origins == ["*"]
    assert settings.CORS_ALLOW_CREDENTIALS is False
