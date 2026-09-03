"""LLM provider configuration handler regressions."""

from unittest.mock import Mock

import handler


def test_discover_models_preserves_v1_endpoint(monkeypatch):
    response = Mock()
    response.json.return_value = {
        "data": [
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o",
            }
        ]
    }
    get = Mock(return_value=response)
    monkeypatch.setattr(handler.httpx, "get", get)

    models = handler.discover_models(
        provider_key="openai",
        api_key="requesty-key",
        endpoint_url="https://router.requesty.ai/v1",
    )

    get.assert_called_once_with(
        "https://router.requesty.ai/v1/models",
        headers={"Authorization": "Bearer requesty-key"},
        timeout=30,
    )
    response.raise_for_status.assert_called_once_with()
    assert models == [
        {
            "model_name": "openai/gpt-4o",
            "display_name": "GPT-4o",
            "context_window": 4096,
            "description": "",
        }
    ]
