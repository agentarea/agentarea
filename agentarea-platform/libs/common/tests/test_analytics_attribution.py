"""A sign-up's channel, from the query its sign-up flow started with (ADR-0047)."""

import pytest
from agentarea_common.analytics.attribution import (
    CHANNELS,
    attribution_from_request_url,
    classify_channel,
    path_pattern,
)
from agentarea_common.config.analytics import AnalyticsSettings
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("referrer_host", "landing_path", "utm_source", "expected"),
    [
        (None, "/", "newsletter", "campaign"),
        ("www.google.com", "/skills/x/", "tg", "campaign"),
        ("www.google.com", "/skills/x/", None, "search"),
        ("yandex.com", "/", None, "search"),
        ("bing.com", "/", None, "search"),
        ("duckduckgo.com", "/", None, "search"),
        ("t.me", "/", None, "social"),
        ("news.ycombinator.com", "/", None, "social"),
        ("habr.com", "/blog/a/", None, "social"),
        ("example.org", "/", None, "referral"),
        (None, "/skills/foo/", None, "skills_catalog"),
        (None, "/ru/skills/foo/", None, "skills_catalog"),
        (None, "/", None, "direct"),
        (None, None, None, "direct"),
    ],
)
def test_classify_channel(referrer_host, landing_path, utm_source, expected):
    assert (
        classify_channel(
            referrer_host=referrer_host,
            landing_path=landing_path,
            utm_source=utm_source,
            own_domains=(),
        )
        == expected
    )


@pytest.mark.parametrize(
    ("referrer_host", "expected"),
    [
        ("example.com", "direct"),
        ("www.example.com", "direct"),
        ("app.example.org", "direct"),
        ("notexample.com", "referral"),
        ("example.com.evil.net", "referral"),
    ],
)
def test_own_domains_and_their_subdomains_are_not_referrers(referrer_host, expected):
    assert (
        classify_channel(
            referrer_host=referrer_host,
            landing_path="/",
            utm_source=None,
            own_domains=("example.com", "example.org"),
        )
        == expected
    )


def test_without_own_domains_every_referrer_is_a_channel():
    assert (
        classify_channel(referrer_host="example.com", landing_path="/", utm_source=None, own_domains=())
        == "referral"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ()),
        ("  ", ()),
        ("example.com", ("example.com",)),
        (" Example.COM , example.org ", ("example.com", "example.org")),
        ("app.example.co.uk", ("app.example.co.uk",)),
    ],
)
def test_own_domains_setting_parses(raw, expected):
    assert AnalyticsSettings(OWN_DOMAINS=raw).OWN_DOMAINS == expected


@pytest.mark.parametrize(
    "raw",
    [
        "example.com,",
        "example.com,,example.org",
        "https://example.com",
        "example.com/path",
        "example.com:443",
        "*.example.com",
        ".example.com",
        "example.com.",
        "localhost",
        "10.0.0.1",
        "-bad.example.com",
        "exa mple.com",
    ],
)
def test_own_domains_setting_rejects_malformed_entries(raw):
    with pytest.raises(ValidationError, match="AGENTAREA_ANALYTICS_OWN_DOMAINS"):
        AnalyticsSettings(OWN_DOMAINS=raw)


def test_path_pattern():
    assert path_pattern("/skills/some-skill/") == "/skills/*"
    assert path_pattern("/ru/skills/x") == "/ru/skills/*"
    assert path_pattern("/blog/post/") == "/blog/*"
    assert path_pattern("/pricing/") == "/pricing/"
    assert path_pattern(None) is None


def test_attribution_from_request_url_reads_landing_params():
    url = (
        "https://auth.example.com/self-service/registration/browser?return_to=x"
        "&aa_ch=search&aa_ref=www.google.com&aa_lh=example.com&aa_lp=%2Fskills%2Fa%2F"
        "&utm_source=&utm_medium=&utm_campaign="
    )
    a = attribution_from_request_url(url, own_domains=())
    assert a.channel == "search"
    assert a.referrer_host == "www.google.com"
    assert a.landing_host == "example.com"
    assert a.landing_path == "/skills/*"
    assert a.utm_source is None


def test_attribution_reclassifies_an_unknown_channel_value():
    a = attribution_from_request_url(
        "https://x/?aa_ch=bogus&aa_lp=%2Fskills%2Fa", own_domains=()
    )
    assert a.channel == "skills_catalog"


def test_attribution_without_params_is_direct():
    for url in (None, "", "not a url", "https://x/self-service/registration/browser"):
        assert attribution_from_request_url(url, own_domains=()).channel == "direct"


def test_values_are_truncated():
    a = attribution_from_request_url("https://x/?utm_source=" + "a" * 200, own_domains=())
    assert a.utm_source == "a" * 64
    assert a.channel == "campaign"


def test_channels_constant():
    assert CHANNELS == {"campaign", "search", "social", "referral", "skills_catalog", "direct"}
