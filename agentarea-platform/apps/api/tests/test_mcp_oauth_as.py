"""Tests for the Hydra OAuth2 proxy path hardening.

The proxy forwards /oauth2/{path} to a fixed, config-driven Hydra host. The host
cannot be changed by the caller, but the user-controlled subpath must not be able
to traverse out of /oauth2/ on that host (partial-SSRF / path-traversal hardening).
"""

from agentarea_api.api.v1.mcp_oauth_as import _is_safe_oauth2_subpath


class TestOAuth2SubpathValidation:
    def test_allows_legitimate_oauth2_paths(self):
        for p in ["token", "revoke", "introspect", "sessions/logout", "userinfo", "device.well"]:
            assert _is_safe_oauth2_subpath(p), p

    def test_rejects_parent_traversal(self):
        for p in ["../admin/clients", "..", "token/../../admin", "a/../../b", "sub/.."]:
            assert not _is_safe_oauth2_subpath(p), p

    def test_rejects_backslash_and_control_chars(self):
        for p in ["foo\\bar", "tok\nen", "tok\ren", "a\x00b"]:
            assert not _is_safe_oauth2_subpath(p), p

    def test_rejects_url_authority_injection(self):
        # Characters that could confuse URL parsing into changing the authority.
        for p in ["@evil.com/path", "evil.com:8080/x", "host/with space"]:
            assert not _is_safe_oauth2_subpath(p), p

    def test_rejects_empty(self):
        assert not _is_safe_oauth2_subpath("")
