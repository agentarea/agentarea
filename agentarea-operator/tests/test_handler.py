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


class _RecordingConn:
    """Records the statements and parameters a sync would issue.

    Every SELECT returns nothing, which is the state that matters here: a model the
    catalog has never heard of, which is the normal case for anything new enough to
    be worth selling.
    """

    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))

        class _Result:
            @staticmethod
            def fetchone():
                return None

        return _Result()

    def params_for(self, fragment):
        for sql, params in self.calls:
            if fragment in sql:
                return params
        raise AssertionError(f"no statement containing {fragment!r} was issued")


def test_an_unknown_model_is_created_with_its_price():
    """The runtime refuses a model whose cost per token is unset.

    So a spec created without one is a model that appears in the picker and then
    fails the moment somebody presses run. This path used to only *activate* specs
    the catalog already had, which meant a model released after the catalog was
    built produced a Synced resource, zero models, and no explanation.
    """
    conn = _RecordingConn()

    handler._upsert_model_spec_and_instance(
        conn,
        "moonshot",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        {
            "model_name": "kimi-k2.5",
            "display_name": "Kimi K2.5",
            "context_window": 262144,
            "input_cost_per_token": 6e-7,
            "output_cost_per_token": 3e-6,
        },
        handler.PLATFORM_WORKSPACE_ID,
    )

    inserted = conn.params_for("INSERT INTO model_specs")
    assert inserted["mn"] == "kimi-k2.5"
    assert inserted["icpt"] == 6e-7, "the model would be unrunnable without this"
    assert inserted["ocpt"] == 3e-6
    assert inserted["cw"] == 262144


def test_the_instance_gets_the_derived_id_so_billing_can_name_it():
    conn = _RecordingConn()

    handler._upsert_model_spec_and_instance(
        conn,
        "moonshot",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        {"model_name": "kimi-k2.5", "input_cost_per_token": 6e-7, "output_cost_per_token": 3e-6},
        handler.PLATFORM_WORKSPACE_ID,
    )

    instance = conn.params_for("INSERT INTO model_instances")
    assert instance["id"] == handler.platform_instance_id("moonshot", "kimi-k2.5")


class _Patch:
    """The part of kopf's patch object these handlers touch."""

    def __init__(self):
        self.status: dict = {}


def test_a_missing_provider_spec_is_retried_rather_than_abandoned(monkeypatch):
    """Provider specs arrive from a catalog import that runs on its own schedule.

    A resource created before that import finishes asks for a provider_key that is
    not in the table yet. Raising PermanentError there meant kopf never looked
    again: the model stayed absent until a human noticed and edited the resource,
    and nothing outside the operator's log said so.
    """
    import kopf
    import pytest

    conn = _RecordingConn()  # every SELECT answers None — no such provider spec
    monkeypatch.setattr(
        handler, "engine", Mock(begin=Mock(return_value=_as_context(conn)))
    )

    with pytest.raises(kopf.TemporaryError, match="openrouter"):
        handler.sync_provider_config(
            {"providerKey": "openrouter", "name": "AgentArea"}, API_KEY, "kimi"
        )


def test_a_permanent_failure_is_written_to_the_resource_status(monkeypatch):
    """The one failure nothing retries has to say so where a human will look.

    Without this the phase keeps its previous value, the GitOps application stays
    green, and the only symptom is a model missing from the picker.
    """
    import kopf
    import pytest

    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: API_KEY)

    def refuse(*_args, **_kwargs):
        raise kopf.PermanentError("SECRET_MANAGER_ENCRYPTION_KEY is not set")

    monkeypatch.setattr(handler, "sync_provider_config", refuse)

    patch = _Patch()
    with pytest.raises(kopf.PermanentError):
        handler.on_provider_config_change(
            spec={"apiKeySecretRef": {"name": "s", "key": "api-key"}},
            meta={"name": "kimi"},
            status={},
            namespace="agentarea",
            patch=patch,
        )

    assert patch.status["phase"] == "Error"
    assert "SECRET_MANAGER_ENCRYPTION_KEY" in patch.status["message"]


def test_a_cross_namespace_secret_ref_is_rejected_without_reading_it(monkeypatch):
    """apiKeySecretRef only ever resolves in the CR's own namespace.

    The operator's Secrets RBAC is scoped there for the same reason: reading a
    Secret on a CR author's behalf into a namespace they may not have Secrets
    access to is a confused-deputy read. A ref naming a different namespace is
    refused outright, not silently narrowed to the CR's own namespace.
    """
    read_secret = Mock(side_effect=AssertionError("must not read a cross-namespace secret"))
    monkeypatch.setattr(handler, "read_secret", read_secret)

    patch = _Patch()
    handler.on_provider_config_change(
        spec={
            "providerKey": "openai",
            "name": "OpenAI",
            "apiKeySecretRef": {"name": "s", "key": "api-key", "namespace": "other-ns"},
        },
        meta={"name": "kimi"},
        status={},
        namespace="agentarea",
        patch=patch,
    )

    read_secret.assert_not_called()
    assert patch.status["phase"] == "Error"
    assert "other-ns" in patch.status["message"]
    assert "agentarea" in patch.status["message"]


def test_a_same_namespace_secret_ref_namespace_is_accepted(monkeypatch):
    import kopf
    import pytest

    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: API_KEY)

    def refuse(*_args, **_kwargs):
        raise kopf.PermanentError("SECRET_MANAGER_ENCRYPTION_KEY is not set")

    monkeypatch.setattr(handler, "sync_provider_config", refuse)

    patch = _Patch()
    with pytest.raises(kopf.PermanentError):
        handler.on_provider_config_change(
            spec={
                "providerKey": "openai",
                "name": "OpenAI",
                "apiKeySecretRef": {"name": "s", "key": "api-key", "namespace": "agentarea"},
            },
            meta={"name": "kimi"},
            status={},
            namespace="agentarea",
            patch=patch,
        )

    # Reached sync_provider_config (and its PermanentError), proving the ref
    # was accepted rather than rejected as cross-namespace.
    assert "SECRET_MANAGER_ENCRYPTION_KEY" in patch.status["message"]


def test_periodic_rediscovery_rejects_a_cross_namespace_secret_ref(monkeypatch):
    read_secret = Mock(side_effect=AssertionError("must not read a cross-namespace secret"))
    monkeypatch.setattr(handler, "read_secret", read_secret)

    patch = _Patch()
    handler.periodic_rediscovery(
        spec={
            "discoverModels": True,
            "apiKeySecretRef": {"name": "s", "key": "api-key", "namespace": "other-ns"},
        },
        meta={"name": "kimi"},
        namespace="agentarea",
        patch=patch,
        status={},
    )

    read_secret.assert_not_called()
    assert patch.status["phase"] == "Error"
    assert "other-ns" in patch.status["message"]


def _as_context(value):
    """Wrap a value so `with x.begin() as v` yields it."""
    ctx = Mock()
    ctx.__enter__ = Mock(return_value=value)
    ctx.__exit__ = Mock(return_value=False)
    return ctx


def test_a_spec_another_workspace_owns_is_not_repriced():
    """uq_model_specs_provider_model has no workspace_id, so the lookup can find a
    tenant's own spec for the same model. Repricing it would silently change what
    their usage of their own key costs them."""
    conn = _RecordingConn()

    handler._upsert_model_spec_and_instance(
        conn,
        "moonshot",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        {"model_name": "kimi-k2.5", "input_cost_per_token": 6e-7},
        handler.PLATFORM_WORKSPACE_ID,
    )

    # The guard is in the statement itself rather than a branch above it.
    update = next((s for s, _ in conn.calls if "UPDATE model_specs" in s), None)
    if update is not None:
        assert "workspace_id = :ws" in update, "an update could reach another workspace's spec"
