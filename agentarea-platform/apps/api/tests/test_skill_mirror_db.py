"""Mirrored skills, the install policy and the repin, against the migrated schema (ADR-0044).

A workspace registry in mirror mode stores every item's package in that
workspace's area when it syncs, and installing an item afterwards reads that
package with no GitHub at all; the installed skill then says which registry
it came from and whether its source still has it. The catalog reads behind install are raw SQL
that must carry each item's registry and trust to the install policy, whose
rules are rows too. The repin reads catalog installs across every workspace
and rewrites each under its own.

Set CATALOG_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import io
import json
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_agents.application.skill_packages import clear_package_cache
from agentarea_agents.application.skill_service import SkillService, repin_all_catalog_installs
from agentarea_agents.infrastructure.github_skill_importer import GitHubFolder
from agentarea_agents.infrastructure.skill_storage_service import (
    SkillStorageService,
    package_digest,
)
from agentarea_api import registry_content
from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from agentarea_registry.application.service import RegistryService
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)
from botocore.exceptions import ClientError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CATALOG_TEST_DATABASE_URL not set")

COMMIT, TREE = "1" * 40, "2" * 40
FOLDER = {"SKILL.md": b"---\nname: pdf\n---\n# PDF", "fill.py": b"print(1)"}
STUB = "---\nname: stub\n---\nA stub. https://github.com/o/r"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    clear_package_cache()
    monkeypatch.setattr(
        "agentarea_common.base.workspace_scoped_repository.grant_resource_owner", AsyncMock()
    )
    monkeypatch.setattr(RegistryService, "_source_etag", staticmethod(lambda _url: None))
    yield
    clear_package_cache()


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            yield s
        await transaction.rollback()
    await engine.dispose()


class MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType=""):  # noqa: N803
        self.objects[Key] = bytes(Body)

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def get_paginator(self, _name):
        return self

    def paginate(self, *, Bucket, Prefix):  # noqa: N803
        yield {
            "Contents": [
                {"Key": k, "Size": len(v)} for k, v in self.objects.items() if k.startswith(Prefix)
            ]
        }

    def delete_objects(self, *, Bucket, Delete):  # noqa: N803
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"], None)

    def under(self, prefix: str) -> dict[str, bytes]:
        return {k[len(prefix) :]: v for k, v in self.objects.items() if k.startswith(prefix)}


def _storage() -> tuple[SkillStorageService, MemoryS3]:
    s3 = MemoryS3()
    storage = SkillStorageService()
    storage._client = s3
    storage._settings = SimpleNamespace(ARTIFACTS_BUCKET="test-bucket")
    return storage, s3


class FolderGitHub:
    def __init__(self, github_token=None):
        self.github_token = github_token

    async def download_folder(self, repo, path, *, ref, tree_sha):
        return GitHubFolder(commit=COMMIT, tree_sha=TREE, files=FOLDER)


class OfflineGitHub:
    async def download_folder(self, repo, path, *, ref, tree_sha):
        raise AssertionError("an install of a mirrored item asks GitHub nothing")


def _context(workspace: str) -> UserContext:
    return UserContext(user_id="u1", workspace_id=workspace)


def _skills(session, workspace, storage, github=None) -> SkillService:
    context = _context(workspace)
    return SkillService(
        RepositoryFactory(session, context),
        context,
        storage_service=storage,
        github_importer=github or OfflineGitHub(),
    )


async def _mirror_registry(session, workspace: str, storage, monkeypatch) -> UUID:
    index = {
        "skills": [
            {"name": "notes", "content": "---\nname: notes\n---\n# Notes", "version": "1"},
            {
                "name": "pdf",
                "source": {
                    "type": "github",
                    "repo": "o/r",
                    "path": "pdf",
                    "ref": COMMIT,
                    "tree_sha": TREE,
                },
            },
        ]
    }
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda _url: index))
    monkeypatch.setattr(registry_content, "GitHubSkillImporter", FolderGitHub)
    context = _context(workspace)
    service = RegistryService(
        RegistryRepository(session, context),
        RegistryItemRepository(session, context),
        server_repo=None,  # type: ignore[arg-type]
        content_mirror=registry_content.registry_content_mirror(storage),
    )
    registry = await service.create_registry(
        name=f"private-{uuid4().hex[:6]}",
        registry_type="skills",
        source_type="url",
        source_url="https://example.test/skills.json",
        scope="workspace",
        workspace_id=workspace,
        mode="mirror",
        trust="private",
    )
    stats = await service.sync_registry(registry.id)
    assert (stats["new_specs"], stats["skipped"]) == (2, 0)
    return registry.id


async def _item_id(session, registry_id: UUID, name: str) -> str:
    return str(
        (
            await session.execute(
                text("SELECT id FROM registry_items WHERE registry_id = :r AND name = :n"),
                {"r": registry_id, "n": name},
            )
        ).scalar_one()
    )


async def test_a_mirrored_workspace_item_installs_from_its_workspaces_store_offline(
    session, monkeypatch
):
    workspace = f"ws-{uuid4()}"
    storage, s3 = _storage()
    with workspace_scope(workspace):
        registry_id = await _mirror_registry(session, workspace, storage, monkeypatch)
        pdf = await _item_id(session, registry_id, "pdf")
        svc = _skills(session, workspace, storage)
        skill = await svc.install_catalog_skill(pdf)

    assert skill.s3_path == f"skills/{workspace}/catalog/{package_digest(FOLDER)}/"
    assert s3.under(skill.s3_path) == FOLDER
    assert s3.under("skills/catalog/") == {}
    assert await svc.read_skill_md(skill) == FOLDER["SKILL.md"].decode()

    await svc.annotate_installs([skill])
    provenance = skill.catalog_provenance
    assert (provenance.registry_scope, provenance.registry_trust) == ("workspace", "private")
    assert provenance.registry_name.startswith("private-")
    assert provenance.removed_upstream is False
    await session.execute(
        text("UPDATE registry_items SET in_source = false WHERE id = :id"), {"id": pdf}
    )
    await svc.annotate_installs([skill])
    assert skill.catalog_provenance.removed_upstream is True


async def _platform_item(session, trust: str, spec: dict, version: str = "1") -> tuple[str, str]:
    registry_id, item_id = str(uuid4()), str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, trust, mode, created_at, updated_at) "
            "VALUES (:id, :name, 'skills', 'managed', 'x', true, :trust, 'upstream', now(), now())"
        ),
        {"id": registry_id, "name": f"test-{registry_id}", "trust": trust},
    )
    await session.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, description, "
            "version, spec, tags, sort_key, featured, registry_type, registry_priority, "
            "registry_active, registry_trust, created_at, updated_at) "
            "SELECT :id, r.id, :external_id, 'stub', 'desc', :version, CAST(:spec AS jsonb), '[]', "
            "'stub', false, r.registry_type, r.recommendation_priority, r.is_active, r.trust, "
            "now(), now() FROM registries r WHERE r.id = :registry_id"
        ),
        {
            "id": item_id,
            "external_id": item_id,
            "registry_id": registry_id,
            "version": version,
            "spec": json.dumps(spec),
        },
    )
    return registry_id, item_id


async def test_a_deny_rule_refuses_an_install_by_the_items_trust(session):
    workspace = f"ws-{uuid4()}"
    storage, _ = _storage()
    _, community = await _platform_item(session, "community", {"content": "# C"})
    _, official = await _platform_item(session, "official", {"content": "# O"})
    await PolicyRuleRepository(session, _context(workspace)).create(
        PolicyRule(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id=workspace,
            target="registry_trust:community",
            effect=PolicyEffect.DENY,
        )
    )

    with workspace_scope(workspace):
        svc = _skills(session, workspace, storage)
        with pytest.raises(CatalogInstallRefusedError):
            await svc.install_catalog_skill(community)
        installed = await svc.install_catalog_skill(official)

    assert installed.registry_item_id is not None
    assert str(installed.registry_item_id) == official


async def _legacy_install(session, workspace: str, item_id: str, content: str) -> str:
    skill_id = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO skills (id, name, slug, source_type, content, s3_path, registry_item_id, "
            "workspace_id, created_by, network_scope, created_at, updated_at) "
            "VALUES (:id, 'stub', :slug, 'content', :content, NULL, :item, :ws, 'u1', "
            "'private', now(), now())"
        ),
        {"id": skill_id, "slug": f"stub-{skill_id[:8]}", "content": content, "item": item_id, "ws": workspace},
    )
    await session.execute(
        text(
            "INSERT INTO registry_item_installs (id, registry_item_id, workspace_id, "
            "installed_entity_id, installed_version, created_at, updated_at) "
            "VALUES (:id, :item, :ws, :skill, '1', now(), now())"
        ),
        {"id": str(uuid4()), "item": item_id, "ws": workspace, "skill": skill_id},
    )
    return skill_id


async def test_the_repin_moves_unedited_installs_in_every_workspace(session):
    storage, s3 = _storage()
    first, second, third = (f"ws-{uuid4()}" for _ in range(3))
    _, item = await _platform_item(session, "community", {"content": STUB}, version="2")
    untouched = await _legacy_install(session, first, item, STUB)
    elsewhere = await _legacy_install(session, second, item, STUB)
    edited = await _legacy_install(session, third, item, STUB + "\nmine")

    @asynccontextmanager
    async def same_session():
        yield session

    results = {r.skill_id: r for _, r in await repin_all_catalog_installs(same_session, storage)}

    assert results[untouched].status == "repinned"
    assert results[elsewhere].status == "repinned"
    assert results[edited].status == "edited"
    rows = {
        str(r.id): r
        for r in (
            await session.execute(
                text(
                    "SELECT s.id, s.s3_path, s.content, rii.installed_version FROM skills s "
                    "JOIN registry_item_installs rii ON rii.installed_entity_id = s.id "
                    "WHERE s.id IN (:a, :b, :c)"
                ),
                {"a": untouched, "b": elsewhere, "c": edited},
            )
        ).all()
    }
    pinned = f"skills/catalog/{package_digest({'SKILL.md': STUB.encode()})}/"
    assert (rows[untouched].s3_path, rows[untouched].content) == (pinned, None)
    assert rows[untouched].installed_version == "2"
    assert rows[elsewhere].s3_path == pinned
    assert (rows[edited].s3_path, rows[edited].content) == (None, STUB + "\nmine")
    assert s3.under(pinned) == {"SKILL.md": STUB.encode()}
