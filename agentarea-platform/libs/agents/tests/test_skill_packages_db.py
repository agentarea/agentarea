"""Skill packages and pinned installs against the real migrated schema (ADR-0044).

The update check is a join of ``registry_items`` and the workspace's
``registry_item_installs`` row, and moving the pin is an upsert on that
table's (item, workspace) unique key; a fake repository has neither. The body
move reads every workspace's pre-package rows in raw SQL, then rewrites each
under its own workspace.

Set CATALOG_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from agentarea_agents.application.skill_packages import (
    clear_package_cache,
    move_all_bodies_to_packages,
)
from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.infrastructure.catalog_skill_repository import CatalogSkillRepository
from agentarea_agents.infrastructure.github_skill_importer import GitHubFolder
from agentarea_agents.infrastructure.skill_storage_service import package_digest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from .fake_s3 import fake_storage

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CATALOG_TEST_DATABASE_URL not set")

OLD_TREE, NEW_TREE = "a" * 40, "b" * 40
FILES = {OLD_TREE: {"SKILL.md": b"# v1"}, NEW_TREE: {"SKILL.md": b"# v2"}}


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_package_cache()
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


@pytest.fixture
def workspace() -> str:
    return f"ws-{uuid4()}"


class TreeGitHub:
    async def download_folder(self, repo, path, *, ref, tree_sha):
        return GitHubFolder(commit="1" * 40, tree_sha=tree_sha, files=FILES[tree_sha])


async def _item(session, version: str) -> str:
    registry_id, item_id = str(uuid4()), str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, created_at, updated_at) "
            "VALUES (:id, :name, 'skills', 'managed', 'x', true, now(), now())"
        ),
        {"id": registry_id, "name": f"test-{registry_id}"},
    )
    spec = {
        "source_type": "github",
        "source": {"type": "github", "repo": "o/r", "path": "pdf", "tree_sha": version},
    }
    await session.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, description, "
            "version, spec, tags, sort_key, featured, registry_type, registry_priority, "
            "registry_active, created_at, updated_at) "
            "SELECT :id, r.id, :external_id, 'pdf', 'desc', :version, CAST(:spec AS jsonb), '[]', "
            "'pdf', false, r.registry_type, r.recommendation_priority, r.is_active, now(), now() "
            "FROM registries r WHERE r.id = :registry_id"
        ),
        {
            "id": item_id,
            "external_id": item_id,
            "registry_id": registry_id,
            "version": version,
            "spec": json.dumps(spec),
        },
    )
    return item_id


async def _skill_row(session, workspace: str, **columns) -> str:
    skill_id = str(uuid4())
    values = {
        "id": skill_id,
        "name": "pdf",
        "slug": f"pdf-{skill_id[:8]}",
        "workspace_id": workspace,
        "content": None,
        "s3_path": None,
        "registry_item_id": None,
        **columns,
    }
    await session.execute(
        text(
            "INSERT INTO skills (id, name, slug, source_type, content, s3_path, registry_item_id, "
            "workspace_id, created_by, network_scope, created_at, updated_at) "
            "VALUES (:id, :name, :slug, 'github', :content, :s3_path, :registry_item_id, "
            ":workspace_id, 'u1', 'private', now(), now())"
        ),
        values,
    )
    return skill_id


def _service(session, workspace: str, storage) -> SkillService:
    context = UserContext(user_id="u1", workspace_id=workspace)
    return SkillService(
        RepositoryFactory(session, context),
        context,
        storage_service=storage,
        github_importer=TreeGitHub(),
    )


async def test_update_all_moves_an_outdated_install_and_its_pin(session, workspace):
    storage, s3 = fake_storage()
    item_id = await _item(session, OLD_TREE)
    old_prefix = await storage.store_catalog_package(FILES[OLD_TREE])
    skill_id = await _skill_row(session, workspace, registry_item_id=item_id, s3_path=old_prefix)
    catalog = CatalogSkillRepository(session, UserContext(user_id="u1", workspace_id=workspace))
    await catalog.mark_installed(item_id, skill_id, OLD_TREE)
    await session.execute(
        text(
            "UPDATE registry_items SET version = :v, "
            "spec = jsonb_set(spec, '{source,tree_sha}', to_jsonb(CAST(:tree AS text))) "
            "WHERE id = :id"
        ),
        {"v": NEW_TREE, "tree": NEW_TREE, "id": item_id},
    )
    assert await catalog.versions_for([item_id]) == {item_id: (NEW_TREE, OLD_TREE)}

    with workspace_scope(workspace):
        svc = _service(session, workspace, storage)
        page, _ = await svc.list_paginated(limit=10, offset=0, include_catalog=False)
        assert [s.update_available for s in page] == [True]
        [result] = await svc.update_all_from_catalog()

    assert result.status == "updated"
    assert await catalog.versions_for([item_id]) == {item_id: (NEW_TREE, NEW_TREE)}
    row = (
        await session.execute(
            text("SELECT s3_path, content FROM skills WHERE id = :id"), {"id": skill_id}
        )
    ).one()
    assert row.s3_path == f"skills/catalog/{package_digest(FILES[NEW_TREE])}/"
    assert row.content is None
    assert s3.under(old_prefix) == FILES[OLD_TREE]

    with workspace_scope(workspace):
        assert await _service(session, workspace, storage).update_all_from_catalog() == []


async def test_bodies_left_in_rows_move_into_packages_in_every_workspace(session, workspace):
    storage, s3 = fake_storage()
    other = f"ws-{uuid4()}"
    legacy = await _skill_row(session, workspace, content="# Legacy")
    legacy_elsewhere = await _skill_row(session, other, content="# Elsewhere")
    packaged = await _skill_row(session, workspace, content="# Stale", s3_path="skills/x/y/")

    @asynccontextmanager
    async def same_session():
        yield session

    moved, failed = await move_all_bodies_to_packages(same_session, storage)

    assert failed == 0
    assert moved >= 2
    rows = {
        str(r.id): r
        for r in (
            await session.execute(
                text("SELECT id, s3_path, content FROM skills WHERE id IN (:a, :b, :c)"),
                {"a": legacy, "b": legacy_elsewhere, "c": packaged},
            )
        ).all()
    }
    assert rows[legacy].s3_path == f"skills/{workspace}/{legacy}/"
    assert rows[legacy].content is None
    assert s3.under(rows[legacy].s3_path) == {"SKILL.md": b"# Legacy"}
    assert rows[legacy_elsewhere].s3_path == f"skills/{other}/{legacy_elsewhere}/"
    assert rows[packaged].s3_path == "skills/x/y/"
