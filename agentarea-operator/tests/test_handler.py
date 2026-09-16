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


def test_platform_ids_match_the_platform_copy_of_the_recipe():
    """These literals also appear in agentarea_common.platform_ids' own test.

    This process holds a second copy of the derivation, because it is a separate
    deployable that imports nothing from the platform packages. Two copies of a
    rule drift, and this one drifting is not an error anyone would see: the ids
    would still be stable, still deterministic, and would simply stop matching the
    rate cards that name them — models running on our provider credit, charging
    nobody, with nothing in any log.

    Pinning the same literals on both sides is what makes that drift a test
    failure. Change these only together with every rate card naming them.
    """
    assert (
        handler.platform_instance_id("openai", "gpt-4o-mini")
        == "481a7f8b-1f56-50c9-bae0-615b2a327d4b"
    )
    assert handler.platform_config_id("openai") == "56ee4e48-5db3-5d4b-ade2-3c06b440f4f8"


def test_the_secret_name_is_one_a_user_cannot_claim():
    """``provider_config_`` is a reserved prefix in the platform's secret naming.

    It does two things, and both are load-bearing. validate_user_secret_name
    refuses the prefix, so no tenant can create a secret under the name the
    operator's credential lives at and have their value served in its place. And
    parse_managed_name reads it back into an owner, which is what stops the secrets
    API offering the row for editing or deletion.
    """
    config_id = handler.platform_config_id("openai")
    assert handler.secret_name_for(config_id) == f"provider_config_{config_id}"


def test_a_missing_encryption_key_refuses_rather_than_storing_the_key_in_the_clear(
    monkeypatch,
):
    """The failure has to be loud: the fallback would be a readable credential.

    provider_configs.api_key is a secret NAME, and the configuration is readable
    from every workspace by design. Writing the key there instead — which is what
    this code did before — puts a live credential in plain text in front of every
    tenant, and the lookup fails anyway because nothing is stored under a name that
    is itself a key.
    """
    import kopf
    import pytest

    monkeypatch.setattr(handler, "ENCRYPTION_KEY", "")

    with pytest.raises(kopf.PermanentError, match="SECRET_MANAGER_ENCRYPTION_KEY"):
        handler.store_api_key(Mock(), "platform", "provider_config_x", API_KEY)
