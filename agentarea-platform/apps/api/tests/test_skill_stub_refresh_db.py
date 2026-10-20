"""Skills holding an old index's stub are refreshed from GitHub, against the migrated schema.

An install from a community shard before packages existed copied the shard's
stub (a pointer to the original SKILL.md) into the skill. The refresh finds
every such skill in every workspace but the platform's, reads the folder the
stub names at its default branch's head and points the skill at a package of
its workspace's, keeping its id, slug and name. The move is a compare-and-set
recorded in the skill's history (the stub as ``migrate``, then ``refresh`` at
the source commit), so it can be rolled back. A skill whose SKILL.md is not a
stub is not touched.

Set CATALOG_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import io
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents.application.skill_packages import clear_package_cache
from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.application.skill_stub_refresh import refresh_all_stub_installs
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubFolder,
    GitHubSourceGoneError,
)
from agentarea_agents.infrastructure.skill_storage_service import (
    SkillStorageService,
    package_digest,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from botocore.exceptions import ClientError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CATALOG_TEST_DATABASE_URL not set")

COMMIT, TREE = "1" * 40, "2" * 40
NAME = "seo-audit--thecraighewitt-seomachine--eee2e76265"
STUB = """---
name: "seo-audit--thecraighewitt-seomachine--eee2e76265"
description: "Audit a page's SEO"
---
Audit a page's SEO

Imported system skill metadata. The original SKILL.md should be reviewed before execution.
Source: https://github.com/TheCraigHewitt/seomachine/blob/main/.claude/skills/seo-audit/SKILL.md
Repository: TheCraigHewitt/seomachine
Path: .claude/skills/seo-audit/SKILL.md
License: NOASSERTION
Distribution: restricted
"""
ORIGINAL = {
    "SKILL.md": b"---\nname: seo-audit\ndescription: Audit SEO, the real one\n---\n# SEO audit\n",
    "checklist.md": b"- titles\n",
}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    clear_package_cache()
    monkeypatch.setattr(
        "agentarea_common.base.workspace_scoped_repository.grant_resource_owner", AsyncMock()
    )
    yield
    clear_package_cache()


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(
            bind=conn,
            expire_on_commit=False,
            sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        ) as s:
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


class FakeGitHub:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[str, str, str | None]] = []

    async def download_folder(self, repo, path, *, ref, tree_sha):
        self.calls.append((repo, path, ref))
        if self.error:
            raise self.error
        return GitHubFolder(commit=COMMIT, tree_sha=TREE, files=ORIGINAL)


def _storage() -> tuple[SkillStorageService, MemoryS3]:
    s3 = MemoryS3()
    storage = SkillStorageService()
    storage._client = s3
    storage._settings = SimpleNamespace(ARTIFACTS_BUCKET="test-bucket")
    return storage, s3


async def _skill(
    session, s3: MemoryS3, workspace: str, body: str, *, in_row: bool = False
) -> str:
    """A skill as an old install left it: its body in the row, or in its own package."""
    skill_id = str(uuid4())
    s3_path = None if in_row else f"skills/{workspace}/{skill_id}/"
    if s3_path:
        s3.objects[f"{s3_path}SKILL.md"] = body.encode()
    await session.execute(
        text(
            "INSERT INTO skills (id, name, slug, description, source_type, content, s3_path, "
            "registry_item_id, workspace_id, created_by, network_scope, created_at, updated_at) "
            "VALUES (:id, :name, :slug, 'Audit a page''s SEO', 'content', :content, :s3, "
            ":item, :ws, 'u1', 'private', now(), now())"
        ),
        {
            "id": skill_id,
            "name": NAME,
            "slug": f"seo-audit-{skill_id[:8]}",
            "content": body if in_row else None,
            "s3": s3_path,
            "item": str(uuid4()),
            "ws": workspace,
        },
    )
    return skill_id


async def _row(session, skill_id: str):
    return (
        await session.execute(
            text(
                "SELECT id, name, slug, description, source_type, source_url, content, "
                "s3_path, registry_item_id, workspace_id FROM skills WHERE id = :id"
            ),
            {"id": skill_id},
        )
    ).one()


async def _history(session, skill_id: str) -> list[tuple[str, str, str | None]]:
    rows = await session.execute(
        text(
            "SELECT reason, s3_path, catalog_version FROM skill_versions "
            "WHERE skill_id = :id ORDER BY created_at, id"
        ),
        {"id": skill_id},
    )
    return [(r.reason, r.s3_path, r.catalog_version) for r in rows.all()]


def _sessions(session):
    @asynccontextmanager
    async def same_session():
        yield session

    return same_session


async def test_a_stub_is_refreshed_from_the_folder_it_names_and_the_rest_left_alone(session):
    storage, s3 = _storage()
    github = FakeGitHub()
    workspace = f"ws-{uuid4()}"
    packaged = await _skill(session, s3, workspace, STUB)
    in_row = await _skill(session, s3, f"ws-{uuid4()}", STUB, in_row=True)
    own = await _skill(session, s3, workspace, "---\nname: mine\n---\n# My own skill")
    before = await _row(session, packaged)

    results = {
        r.skill_id: r
        for _, r in await refresh_all_stub_installs(_sessions(session), storage, github=github)
    }

    assert set(results) == {packaged, in_row}
    assert {r.status for r in results.values()} == {"refreshed"}
    assert github.calls[0] == ("TheCraigHewitt/seomachine", ".claude/skills/seo-audit", None)
    after = await _row(session, packaged)
    pinned = f"skills/{workspace}/packages/{package_digest(ORIGINAL)}/"
    stub_package = f"skills/{workspace}/packages/{package_digest({'SKILL.md': STUB.encode()})}/"
    assert (after.id, after.slug, after.name) == (before.id, before.slug, before.name)
    assert after.s3_path == pinned and after.content is None
    assert after.source_type == "github" and after.registry_item_id is None
    assert await _history(session, packaged) == [
        ("migrate", stub_package, None),
        ("refresh", pinned, COMMIT),
    ]
    assert after.source_url == (
        f"https://github.com/TheCraigHewitt/seomachine/tree/{COMMIT}/.claude/skills/seo-audit"
    )
    assert after.description == "Audit SEO, the real one"
    assert s3.under(pinned) == ORIGINAL
    assert results[packaged].commit == COMMIT
    assert after.name == NAME
    assert "'seo-audit'" in (results[packaged].detail or "")
    assert (await _row(session, in_row)).content is None
    assert [reason for reason, _, _ in await _history(session, in_row)] == ["migrate", "refresh"]
    assert (await _row(session, own)).s3_path == f"skills/{workspace}/{own}/"


async def test_a_second_run_finds_nothing(session):
    storage, s3 = _storage()
    await _skill(session, s3, f"ws-{uuid4()}", STUB)
    sessions = _sessions(session)
    await refresh_all_stub_installs(sessions, storage, github=FakeGitHub())

    assert await refresh_all_stub_installs(sessions, storage, github=FakeGitHub()) == []


async def test_a_folder_gone_from_github_is_reported_not_found_and_changes_nothing(session):
    storage, s3 = _storage()
    skill = await _skill(session, s3, f"ws-{uuid4()}", STUB)
    before = await _row(session, skill)

    [(_, result)] = await refresh_all_stub_installs(
        _sessions(session), storage, github=FakeGitHub(GitHubSourceGoneError("404"))
    )

    assert result.status == "not_found"
    assert await _row(session, skill) == before
    assert await _history(session, skill) == []


async def test_a_refresh_the_install_policy_refuses_is_reported_and_changes_nothing(session):
    storage, s3 = _storage()
    workspace = f"ws-{uuid4()}"
    skill = await _skill(session, s3, workspace, STUB)
    with workspace_scope(workspace):
        await PolicyRuleRepository(session, UserContext(user_id="u1", workspace_id=workspace)).create(
            PolicyRule(
                subject_type=PolicySubjectType.WORKSPACE,
                subject_id=workspace,
                target="registry:github",
                effect=PolicyEffect.DENY,
            )
        )
    before = await _row(session, skill)
    github = FakeGitHub()

    [(_, result)] = await refresh_all_stub_installs(_sessions(session), storage, github=github)

    assert result.status == "refused"
    assert github.calls == []
    assert await _row(session, skill) == before
    assert await _history(session, skill) == []


async def test_a_dry_run_lists_the_stubs_and_changes_nothing(session):
    storage, s3 = _storage()
    skill = await _skill(session, s3, f"ws-{uuid4()}", STUB, in_row=True)
    before, objects = await _row(session, skill), dict(s3.objects)
    github = FakeGitHub()

    [(_, result)] = await refresh_all_stub_installs(
        _sessions(session), storage, github=github, dry_run=True
    )

    assert result.status == "would_refresh"
    assert github.calls == []
    assert await _row(session, skill) == before
    assert await _history(session, skill) == []
    assert s3.objects == objects


async def test_the_platform_workspaces_stub_copies_are_skipped(session):
    storage, s3 = _storage()
    await _skill(session, s3, PLATFORM_WORKSPACE_ID, STUB, in_row=True)
    github = FakeGitHub()

    results = await refresh_all_stub_installs(_sessions(session), storage, github=github)

    assert all(ws != PLATFORM_WORKSPACE_ID for ws, _ in results)
    assert github.calls == []


async def test_a_refresh_is_rolled_back_to_the_stub_like_any_version(session):
    storage, s3 = _storage()
    workspace = f"ws-{uuid4()}"
    skill = await _skill(session, s3, workspace, STUB)
    await refresh_all_stub_installs(_sessions(session), storage, github=FakeGitHub())
    stub_version = (
        await session.execute(
            text("SELECT id FROM skill_versions WHERE skill_id = :id AND reason = 'migrate'"),
            {"id": skill},
        )
    ).scalar_one()
    context = UserContext(user_id="u1", workspace_id=workspace)

    with workspace_scope(workspace):
        svc = SkillService(RepositoryFactory(session, context), context, storage_service=storage)
        rolled_back = await svc.rollback(skill, str(stub_version))
        assert await svc.read_skill_md(rolled_back) == STUB
