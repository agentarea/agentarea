"""A mirror-mode skills registry stores every item's content when it syncs (ADR-0044).

The sync hands each item to the content mirror it was given and keeps where
the package went in the item's spec, so an install needs no network. An item
whose content could not be stored is skipped and the source is read again by
the next run; an item whose entry did not change keeps its package without
being stored again.
"""

import logging
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)

from .test_github_skill_registry import REPO_FILES, StubGitHub

INDEX = {
    "skills": [
        {"name": "pdf", "content": "---\nname: pdf\n---\n# PDF", "version": "1"},
        {"name": "xlsx", "content": "---\nname: xlsx\n---\n# XLSX", "version": "1"},
    ]
}


class RecordingMirror:
    """Opened once per sync with the registry and its token; stores per item."""

    def __init__(self, fail: set[str] | None = None):
        self.fail = fail or set()
        self.opened: list[tuple] = []
        self.stored: list[dict] = []

    def __call__(self, registry, token):
        self.opened.append((registry.id, token))

        async def store(spec):
            body = spec.get("content") or spec["source"]["path"]
            if any(name in body for name in self.fail):
                raise RuntimeError(f"cannot store {body}")
            self.stored.append(spec)
            return {"s3_path": f"skills/catalog/{len(self.stored):064d}/", "source_url": None}

        return store


@pytest.fixture
def index(monkeypatch):
    state = {"data": INDEX}
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda _url: state["data"]))
    return state


async def _registry(db_session, **fields) -> Registry:
    record = Registry(
        name=f"skills-{uuid4().hex[:6]}",
        registry_type="skills",
        source_type="url",
        source_url="https://example.test/skills.json",
        **{"mode": "mirror", **fields},
    )
    db_session.add(record)
    await db_session.commit()
    return record


def _service(db_session, mirror=None, **kwargs) -> RegistryService:
    return RegistryService(
        RegistryRepository(db_session),
        RegistryItemRepository(db_session),
        server_repo=None,
        content_mirror=mirror,
        **kwargs,
    )


async def _specs(db_session, registry) -> dict[str, dict]:
    items = await RegistryItemRepository(db_session).list_by_registry(registry.id)
    return {i.external_id: i.spec for i in items}


async def test_a_sync_stores_every_items_package_and_keeps_where(db_session, index):
    registry = await _registry(db_session)
    mirror = RecordingMirror()

    stats = await _service(db_session, mirror).sync_registry(registry.id)

    assert (stats["new_specs"], stats["skipped"]) == (2, 0)
    assert mirror.opened == [(registry.id, None)]
    specs = await _specs(db_session, registry)
    assert {name: spec["package"]["s3_path"] for name, spec in specs.items()} == {
        "pdf": f"skills/catalog/{1:064d}/",
        "xlsx": f"skills/catalog/{2:064d}/",
    }
    assert specs["pdf"]["content"].endswith("# PDF")


async def test_an_unchanged_item_keeps_its_package_without_storing_it_again(db_session, index):
    registry = await _registry(db_session)
    mirror = RecordingMirror()
    service = _service(db_session, mirror)
    await service.sync_registry(registry.id)

    index["data"] = {
        "skills": [INDEX["skills"][0], {**INDEX["skills"][1], "content": "# XLSX v2"}]
    }
    await service.sync_registry(registry.id, force=True)

    assert [s.get("content") for s in mirror.stored][2:] == ["# XLSX v2"]
    specs = await _specs(db_session, registry)
    assert specs["pdf"]["package"]["s3_path"] == f"skills/catalog/{1:064d}/"
    assert specs["xlsx"]["package"]["s3_path"] == f"skills/catalog/{3:064d}/"


async def test_an_item_that_could_not_be_stored_is_skipped_and_retried(
    db_session, index, caplog
):
    registry = await _registry(db_session)
    service = _service(db_session, RecordingMirror(fail={"XLSX"}))

    with caplog.at_level(logging.WARNING):
        stats = await service.sync_registry(registry.id)

    assert (stats["new_specs"], stats["skipped"]) == (1, 1)
    assert stats["skipped_items"][0]["external_id"] == "xlsx"
    assert any(r.exc_info for r in caplog.records if "xlsx" in r.getMessage())
    assert set(await _specs(db_session, registry)) == {"pdf"}
    await db_session.refresh(registry)
    assert registry.source_etag is None


async def test_a_new_version_that_could_not_be_stored_leaves_the_last_one(db_session, index):
    registry = await _registry(db_session)
    await _service(db_session, RecordingMirror()).sync_registry(registry.id)

    index["data"] = {
        "skills": [{**INDEX["skills"][0], "content": "# PDF v2", "version": "2"}, INDEX["skills"][1]]
    }
    stats = await _service(db_session, RecordingMirror(fail={"PDF v2"})).sync_registry(
        registry.id, force=True
    )

    assert stats["skipped"] == 1
    pdf = (await _specs(db_session, registry))["pdf"]
    assert pdf["content"].endswith("# PDF")
    assert pdf["package"]["s3_path"] == f"skills/catalog/{1:064d}/"


async def test_an_upstream_registry_stores_no_content(db_session, index):
    registry = await _registry(db_session, mode="upstream")
    mirror = RecordingMirror()

    await _service(db_session, mirror).sync_registry(registry.id)

    assert mirror.opened == []
    assert all("package" not in s for s in (await _specs(db_session, registry)).values())


async def test_a_mirror_registry_without_a_content_store_fails_the_sync(db_session, index):
    registry = await _registry(db_session)

    with pytest.raises(ValueError, match="mirror"):
        await _service(db_session).sync_registry(registry.id)


@pytest_asyncio.fixture
async def private_repo(db_session):
    record = Registry(
        name="acme-private",
        registry_type="skills",
        source_type="github",
        source_url="acme/skills",
        scope="workspace",
        workspace_id="ws-acme",
        mode="mirror",
        trust="private",
        credentials_secret_ref=uuid4(),
    )
    db_session.add(record)
    await db_session.commit()
    return record


async def test_a_private_repository_is_mirrored_with_its_token(db_session, private_repo):
    async def resolve(_registry):
        return "ghp_secret"

    mirror = RecordingMirror()
    service = _service(
        db_session,
        mirror,
        credentials_resolver=resolve,
        github_source_factory=lambda _token: StubGitHub(REPO_FILES),
    )

    stats = await service.sync_registry(private_repo.id)

    assert stats["new_specs"] == 3
    assert mirror.opened == [(private_repo.id, "ghp_secret")]
    assert {s["source"]["path"] for s in mirror.stored} == {
        "skills/pdf",
        "skills/xlsx",
        "other/notes",
    }


async def test_switching_a_registry_to_mirror_reads_its_source_again(db_session, index):
    registry = await _registry(db_session, mode="upstream")
    await _service(db_session).sync_registry(registry.id)
    await RegistryRepository(db_session).update(registry.id, source_etag="2:v1")

    updated = await _service(db_session).update_registry(registry.id, mode="mirror")

    assert updated.source_etag is None
