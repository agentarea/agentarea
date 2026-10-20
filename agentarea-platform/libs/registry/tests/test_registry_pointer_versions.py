"""An installed pointer whose index names no tree SHA still detects updates (ADR-0044).

Such an item's index version is ``latest``, and an install pins the folder's
tree SHA computed from what it fetched. A sync asks the source what tree the
folder is now (token-free, a bounded number per sync) for the items some
workspace installed, and keeps that as the item's version, so the install's pin
and the item's version compare as they do for an index that carries tree SHAs.
"""

from uuid import uuid4

import pytest_asyncio
from agentarea_registry.application import service as service_module
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry, RegistryItemInstall
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)

PINNED = "a" * 40


def _index(*names: str, tree_sha: str | None = None) -> dict:
    source = {"type": "github", "repo": "owner/repo"}
    if tree_sha:
        source["tree_sha"] = tree_sha
    return {"skills": [{"name": n, "source": {**source, "path": f"skills/{n}"}} for n in names]}


class Upstream:
    """The folder trees the source holds now, and who asked."""

    def __init__(self, trees: dict[str, str]):
        self.trees = trees
        self.asked: list[str] = []

    async def __call__(self, source: dict) -> str:
        self.asked.append(source["path"])
        return self.trees[source["path"]]


@pytest_asyncio.fixture
async def community(db_session, monkeypatch):
    registry = Registry(
        name="community",
        registry_type="skills",
        source_type="url",
        source_url="https://example.test/skills.json",
        mode="upstream",
        trust="community",
    )
    db_session.add(registry)
    await db_session.commit()
    index = {"data": _index("pdf", "xlsx")}
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda _u: index["data"]))
    return registry, index


def _service(db_session, upstream) -> RegistryService:
    return RegistryService(
        RegistryRepository(db_session),
        RegistryItemRepository(db_session),
        server_repo=None,
        pointer_version=upstream,
    )


async def _install(db_session, registry, name: str, pinned: str) -> str:
    items = await RegistryItemRepository(db_session).list_by_registry(registry.id)
    item = next(i for i in items if i.external_id == name)
    install = RegistryItemInstall(
        registry_item_id=item.id,
        workspace_id="w1",
        installed_entity_id=uuid4(),
        installed_version=pinned,
    )
    db_session.add(install)
    await db_session.commit()
    return str(item.id)


async def _versions(db_session, registry) -> dict[str, str]:
    items = await RegistryItemRepository(db_session).list_by_registry(registry.id)
    return {i.external_id: i.version for i in items}


async def test_an_installed_pointer_takes_the_folders_current_tree_as_its_version(
    db_session, community
):
    registry, _ = community
    upstream = Upstream({"skills/pdf": PINNED})
    service = _service(db_session, upstream)
    await service.sync_registry(registry.id)
    assert upstream.asked == []  # nothing installed yet: nothing to compare

    await _install(db_session, registry, "pdf", PINNED)
    upstream.trees["skills/pdf"] = "b" * 40
    stats = await service.sync_registry(registry.id)

    assert upstream.asked == ["skills/pdf"]
    assert await _versions(db_session, registry) == {"pdf": "b" * 40, "xlsx": "latest"}
    assert stats["pointers_checked"] == 1


async def test_the_check_runs_when_the_index_itself_is_unchanged(
    db_session, community, monkeypatch
):
    registry, _ = community
    monkeypatch.setattr(RegistryService, "_source_etag", staticmethod(lambda _url: '"v1"'))
    upstream = Upstream({"skills/pdf": PINNED})
    service = _service(db_session, upstream)
    await service.sync_registry(registry.id)
    await _install(db_session, registry, "pdf", PINNED)

    upstream.trees["skills/pdf"] = "c" * 40
    stats = await service.sync_registry(registry.id)

    assert stats["source_unchanged"] is True
    assert (await _versions(db_session, registry))["pdf"] == "c" * 40


async def test_a_resync_of_the_index_keeps_the_checked_version(db_session, community):
    registry, index = community
    upstream = Upstream({"skills/pdf": PINNED})
    service = _service(db_session, upstream)
    await service.sync_registry(registry.id)
    await _install(db_session, registry, "pdf", PINNED)
    await service.sync_registry(registry.id)

    index["data"] = {"skills": [*_index("pdf", "xlsx")["skills"], *_index("docx")["skills"]]}
    upstream.trees.clear()  # the check fails: what is left is what the index sync kept
    await service.sync_registry(registry.id)

    assert (await _versions(db_session, registry))["pdf"] == PINNED


async def test_an_index_that_carries_tree_shas_is_not_asked_about(db_session, community):
    registry, index = community
    index["data"] = _index("pdf", tree_sha="d" * 40)
    upstream = Upstream({})
    service = _service(db_session, upstream)
    await service.sync_registry(registry.id)
    await _install(db_session, registry, "pdf", "d" * 40)

    await service.sync_registry(registry.id)

    assert upstream.asked == []
    assert (await _versions(db_session, registry))["pdf"] == "d" * 40


async def test_the_checks_per_sync_are_bounded_and_a_failure_skips_only_that_item(
    db_session, community, monkeypatch
):
    registry, index = community
    index["data"] = _index("a", "b", "c")
    monkeypatch.setattr(service_module, "MAX_POINTER_CHECKS", 2)

    class Flaky(Upstream):
        async def __call__(self, source):
            self.asked.append(source["path"])
            if source["path"] == "skills/a":
                raise RuntimeError("GitHub answered 502")
            return "e" * 40

    upstream = Flaky({})
    service = _service(db_session, upstream)
    await service.sync_registry(registry.id)
    for name in ("a", "b", "c"):
        await _install(db_session, registry, name, PINNED)

    await service.sync_registry(registry.id)

    assert len(upstream.asked) == 2
    versions = await _versions(db_session, registry)
    assert versions["a"] == "latest"
    assert sorted(versions.values()).count("e" * 40) == 1


async def test_a_throttled_check_stops_the_rest_of_this_syncs_checks(db_session, community):
    from agentarea_common.github_git import GitHubGitRateLimitError

    registry, _ = community

    class Throttled(Upstream):
        async def __call__(self, source):
            self.asked.append(source["path"])
            raise GitHubGitRateLimitError("throttled")

    upstream = Throttled({})
    service = _service(db_session, upstream)
    await service.sync_registry(registry.id)
    for name in ("pdf", "xlsx"):
        await _install(db_session, registry, name, PINNED)

    await service.sync_registry(registry.id)

    assert upstream.asked == ["skills/pdf"]


async def test_a_mirrored_pointer_without_a_tree_sha_is_versioned_by_the_tree_it_stored(
    db_session, community
):
    registry, _ = community
    await RegistryRepository(db_session).update(registry.id, mode="mirror")

    def mirror(_registry, _token):
        async def store(spec):
            return {"s3_path": f"skills/catalog/{'0' * 64}/", "tree_sha": "f" * 40}

        return store

    service = RegistryService(
        RegistryRepository(db_session),
        RegistryItemRepository(db_session),
        server_repo=None,
        content_mirror=mirror,
        pointer_version=Upstream({}),
    )

    await service.sync_registry(registry.id)

    assert await _versions(db_session, registry) == {"pdf": "f" * 40, "xlsx": "f" * 40}
