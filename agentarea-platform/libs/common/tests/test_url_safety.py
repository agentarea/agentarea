"""Tests for the outbound-URL SSRF guard.

The guard hardcodes no provider IPs; it rejects the universal IANA non-public
address classes (RFC1918 private, loopback, link-local, reserved, multicast,
unspecified) so it stays portable across clouds (DO, AWS, GCP, Hetzner, on-prem).
"""

import pytest
from agentarea_common.utils.url_safety import UnsafeUrlError, validate_outbound_url


class TestSchemeValidation:
    def test_rejects_non_http_scheme(self):
        for url in ["file:///etc/passwd", "gopher://x/", "ftp://host/x"]:
            with pytest.raises(UnsafeUrlError):
                validate_outbound_url(url)

    def test_rejects_missing_host(self):
        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("http:///models")

    def test_allows_http_and_https(self):
        # Public IP literals need no DNS; both schemes accepted.
        validate_outbound_url("http://8.8.8.8/v1/models")
        validate_outbound_url("https://1.1.1.1/v1/models")


class TestBlockedAddressClasses:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",  # loopback
            "http://169.254.169.254/latest/meta-data/",  # link-local / cloud metadata
            "http://10.0.0.5/x",  # RFC1918
            "http://172.16.0.1/x",  # RFC1918
            "http://192.168.1.1/x",  # RFC1918
            "http://0.0.0.0/x",  # unspecified
            "http://[::1]/x",  # IPv6 loopback
            "http://[fd00::1]/x",  # IPv6 ULA (private)
        ],
    )
    def test_rejects_non_public_targets(self, url):
        with pytest.raises(UnsafeUrlError):
            validate_outbound_url(url)

    def test_rejects_localhost_by_name(self):
        # Resolves offline via /etc/hosts to loopback.
        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("http://localhost:11434/api/tags")

    def test_allows_public_ip_literal(self):
        validate_outbound_url("https://93.184.216.34/v1/models")


class TestAllowPrivateOptOut:
    def test_allow_private_skips_ip_checks(self):
        # Self-host opt-out: private endpoints permitted, scheme still enforced.
        validate_outbound_url("http://127.0.0.1:11434/api/tags", allow_private=True)
        validate_outbound_url("http://192.168.1.50/v1/models", allow_private=True)

    def test_allow_private_still_enforces_scheme(self):
        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("file:///etc/passwd", allow_private=True)
