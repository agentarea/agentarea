"""Provider discovery API contract regressions."""

from agentarea_api.api.v1.provider_configs import DiscoverPreviewRequest


def test_discover_preview_does_not_accept_client_private_endpoint_bypass():
    assert "allow_private_endpoint" not in DiscoverPreviewRequest.model_fields


def test_discover_preview_api_key_is_optional_for_keyless_endpoints():
    request = DiscoverPreviewRequest(provider_key="openai", endpoint_url="https://example.com")

    assert request.api_key is None
