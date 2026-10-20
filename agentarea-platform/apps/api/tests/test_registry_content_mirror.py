"""The content mirror a sync is given stores each registry's packages in its own area,
reading a private source with the registry's token.
"""

from types import SimpleNamespace

from agentarea_api import registry_content


async def test_each_registry_is_mirrored_into_its_own_area_with_its_token(monkeypatch):
    opened: list[tuple] = []

    class Mirror:
        def __init__(self, storage, github, *, workspace_id):
            opened.append((storage, github.github_token, workspace_id))

    monkeypatch.setattr(registry_content, "CatalogMirror", Mirror)
    storage = object()
    open_mirror = registry_content.registry_content_mirror(storage)  # type: ignore[arg-type]

    open_mirror(SimpleNamespace(scope="workspace", workspace_id="ws-1"), "ghp_secret")
    open_mirror(SimpleNamespace(scope="platform", workspace_id=None), None)

    assert opened == [(storage, "ghp_secret", "ws-1"), (storage, None, None)]


def test_a_mirror_without_object_storage_fails_the_sync_by_name(monkeypatch):
    import pytest
    from agentarea_registry.application.service import (
        RegistryConfigurationError,
        sync_error_message,
    )

    for name in ("AGENTAREA_S3_ACCESS_KEY", "AGENTAREA_S3_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    open_mirror = registry_content.registry_content_mirror()

    with pytest.raises(RegistryConfigurationError) as refused:
        open_mirror(SimpleNamespace(scope="platform", workspace_id=None), None)

    assert "AGENTAREA_S3_ACCESS_KEY" in sync_error_message(refused.value)
