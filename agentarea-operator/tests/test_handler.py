"""LLM provider configuration handler regressions."""

from unittest.mock import Mock

import handler

API_KEY = "token"  # pragma: allowlist secret


def _mock_get(monkeypatch):
    response = Mock()
    response.json.return_value = {"data": [{"id": "openai/gpt-4o", "name": "GPT-4o"}]}
    get = Mock(return_value=response)
    monkeypatch.setattr(handler.httpx, "get", get)
    return get


def test_discovery_does_not_double_the_version_prefix(monkeypatch):
    """An endpoint that already names /v1 must not become /v1/v1.

    OpenAI-compatible routers are configured with the version in the URL. The
    resulting 404 was swallowed into an empty model list, so a broken URL was
    indistinguishable from a provider that publishes nothing.
    """
    get = _mock_get(monkeypatch)

    models = handler.discover_models(
        provider_key="openai",
        api_key=API_KEY,
        endpoint_url="https://router.example.com/v1",
    )

    get.assert_called_once_with(
        "https://router.example.com/v1/models",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=30,
    )
    assert [m["model_name"] for m in models] == ["openai/gpt-4o"]


def test_discovery_adds_the_version_prefix_when_the_endpoint_omits_it(monkeypatch):
    get = _mock_get(monkeypatch)

    handler.discover_models(
        provider_key="openai", api_key=API_KEY, endpoint_url="https://router.example.com"
    )

    assert get.call_args.args[0] == "https://router.example.com/v1/models"


def test_default_provider_base_still_gets_the_version_prefix(monkeypatch):
    get = _mock_get(monkeypatch)

    handler.discover_models(provider_key="openai", api_key=API_KEY, endpoint_url=None)

    assert get.call_args.args[0] == "https://api.openai.com/v1/models"


def test_anthropic_keeps_its_own_auth_header(monkeypatch):
    get = _mock_get(monkeypatch)

    handler.discover_models(provider_key="anthropic", api_key=API_KEY, endpoint_url=None)

    get.assert_called_once_with(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01"},
        timeout=30,
    )
