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

import io
import json
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_agents.application.skill_packages import (
    clear_package_cache,
    move_all_bodies_to_packages,
)
from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.infrastructure.catalog_skill_repository import CatalogSkillRepository
from agentarea_agents.infrastructure.github_skill_importer import GitHubFolder
from agentarea_agents.infrastructure.skill_storage_service import (
    SkillStorageService,
    package_digest,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from botocore.exceptions import ClientError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


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


class MemoryS3:
    """The S3 calls the storage service makes, in memory.

    Inline rather than imported from ``fake_s3``: check-db collects suites of
    several ``tests`` packages in one run, where a relative import does not
    resolve.
    """

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

    def under(self, prefix: str) -> dict[str, bytes]:
        return {k[len(prefix) :]: v for k, v in self.objects.items() if k.startswith(prefix)}


def fake_storage() -> tuple[SkillStorageService, MemoryS3]:
    s3 = MemoryS3()
    storage = SkillStorageService()
    storage._client = s3
    storage._settings = SimpleNamespace(ARTIFACTS_BUCKET="test-bucket")
    return storage, s3


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


def _own(workspace: str, files: dict[str, bytes]) -> str:
    return f"skills/{workspace}/packages/{package_digest(files)}/"


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
    from agentarea_common.constants import PLATFORM_WORKSPACE_ID

    storage, s3 = fake_storage()
    other = f"ws-{uuid4()}"
    shared = f"skills/catalog/{'c' * 64}/"
    s3.objects.update({f"{shared}SKILL.md": b"# Imported", f"{shared}fill.py": b"print(1)"})
    legacy = await _skill_row(session, workspace, content="# Legacy")
    legacy_elsewhere = await _skill_row(session, other, content="# Elsewhere")
    # Edited after an import: the edit lived only in the row, the prompt read it.
    edited = await _skill_row(session, workspace, content="# Edited", s3_path=shared)
    unedited = await _skill_row(session, workspace, content="# Imported", s3_path=shared)
    # The platform workspace's stub copies are deleted by the reconcile.
    stub = await _skill_row(session, PLATFORM_WORKSPACE_ID, content="# Stub")

    @asynccontextmanager
    async def same_session():
        yield session

    moved, failed = await move_all_bodies_to_packages(same_session, storage)

    assert failed == 0
    assert moved >= 4
    rows = {
        str(r.id): r
        for r in (
            await session.execute(
                text("SELECT id, s3_path, content FROM skills WHERE id IN (:a, :b, :c, :d, :e)"),
                {"a": legacy, "b": legacy_elsewhere, "c": edited, "d": unedited, "e": stub},
            )
        ).all()
    }
    assert rows[legacy].s3_path == _own(workspace, {"SKILL.md": b"# Legacy"})
    assert rows[legacy].content is None
    assert s3.under(rows[legacy].s3_path) == {"SKILL.md": b"# Legacy"}
    assert rows[legacy_elsewhere].s3_path == _own(other, {"SKILL.md": b"# Elsewhere"})
    edited_files = {"SKILL.md": b"# Edited", "fill.py": b"print(1)"}
    assert (rows[edited].s3_path, rows[edited].content) == (_own(workspace, edited_files), None)
    assert s3.under(rows[edited].s3_path) == edited_files
    assert s3.under(shared) == {"SKILL.md": b"# Imported", "fill.py": b"print(1)"}
    assert (rows[unedited].s3_path, rows[unedited].content) == (shared, None)
    assert (rows[stub].s3_path, rows[stub].content) == (None, "# Stub")


async def _versions(session, skill_id: str) -> list[tuple[str, str, str | None]]:
    rows = await session.execute(
        text(
            "SELECT reason, s3_path, digest FROM skill_versions WHERE skill_id = :id "
            "ORDER BY created_at, id"
        ),
        {"id": skill_id},
    )
    return [tuple(r) for r in rows.all()]


async def test_edits_are_versions_and_a_rollback_moves_the_pointer_back(session, workspace):
    storage, s3 = fake_storage()
    v1_path = await storage.store_workspace_package({"SKILL.md": b"# v1"}, workspace)
    skill_id = await _skill_row(session, workspace, s3_path=v1_path)
    with workspace_scope(workspace):
        svc = _service(session, workspace, storage)
        repo = svc._get_repository()
        await repo.add_version(await repo.get_by_id(skill_id), reason="create")
        skill = await svc.set_content(skill_id, "# v2")
        [first, _] = await svc.list_versions(skill.id)
        rolled = await svc.rollback(skill.id, first.id)

    v1, v2 = {"SKILL.md": b"# v1"}, {"SKILL.md": b"# v2"}
    assert rolled.s3_path == _own(workspace, v1)
    assert await _versions(session, str(skill.id)) == [
        ("create", _own(workspace, v1), package_digest(v1)),
        ("edit", _own(workspace, v2), package_digest(v2)),
        ("rollback", _own(workspace, v1), package_digest(v1)),
    ]
    assert s3.under(_own(workspace, v2)) == v2


async def test_copies_move_into_packages_and_only_the_moved_ones_are_deleted(session, workspace):
    from agentarea_agents.application.skill_packages import (
        delete_moved_own_copies,
        move_all_own_copies_to_packages,
    )

    from datetime import timedelta

    now = timedelta(seconds=-60)  # "moved before a minute from now": everything moved so far
    storage, s3 = fake_storage()
    copied = await _skill_row(session, workspace)
    await session.execute(
        text("UPDATE skills SET s3_path = :p WHERE id = :id"),
        {"p": f"skills/{workspace}/{copied}/", "id": copied},
    )
    s3.objects[f"skills/{workspace}/{copied}/SKILL.md"] = b"# Copied"

    @asynccontextmanager
    async def same_session():
        yield session

    assert await delete_moved_own_copies(same_session, storage, dry_run=True, min_age=now) == (0, 0)
    moved, failed = await move_all_own_copies_to_packages(same_session, storage)

    assert (moved, failed) == (1, 0)
    package = _own(workspace, {"SKILL.md": b"# Copied"})
    row = (await session.execute(text("SELECT s3_path FROM skills WHERE id = :id"), {"id": copied})).one()
    assert row.s3_path == package
    assert await _versions(session, copied) == [
        ("migrate", package, package_digest({"SKILL.md": b"# Copied"}))
    ]
    # The copy stays until the explicit command, and a dry run deletes nothing.
    assert s3.under(f"skills/{workspace}/{copied}/") == {"SKILL.md": b"# Copied"}
    # Moved just now: kept by the default age, deleted only once old enough.
    assert await delete_moved_own_copies(same_session, storage) == (0, 0)
    assert await delete_moved_own_copies(same_session, storage, dry_run=True, min_age=now) == (1, 1)
    assert s3.under(f"skills/{workspace}/{copied}/") == {"SKILL.md": b"# Copied"}
    s3.delete_objects = lambda *, Bucket, Delete: [  # noqa: N803
        s3.objects.pop(o["Key"]) for o in Delete["Objects"]
    ]
    assert await delete_moved_own_copies(same_session, storage, min_age=now) == (1, 1)
    assert s3.under(f"skills/{workspace}/{copied}/") == {}
    assert s3.under(package) == {"SKILL.md": b"# Copied"}


async def test_the_migration_starts_each_packaged_skills_history(session, workspace):
    import importlib.util
    from pathlib import Path

    migration_file = next(
        (Path(__file__).resolve().parents[3] / "apps" / "api" / "alembic" / "versions").glob(
            "*_skill_versions.py"
        )
    )
    spec = importlib.util.spec_from_file_location("skill_versions_migration", migration_file)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    item_id = await _item(session, OLD_TREE)
    own = await _skill_row(session, workspace, s3_path=f"skills/{workspace}/packages/{'d' * 64}/")
    installed = await _skill_row(
        session, workspace, s3_path=f"skills/catalog/{'e' * 64}/", registry_item_id=item_id
    )
    await CatalogSkillRepository(
        session, UserContext(user_id="u1", workspace_id=workspace)
    ).mark_installed(item_id, installed, OLD_TREE)
    copy = await _skill_row(session, workspace)
    await session.execute(
        text("UPDATE skills SET s3_path = :p WHERE id = :id"),
        {"p": f"skills/{workspace}/{copy}/", "id": copy},
    )

    await session.execute(text(migration.BACKFILL))
    await session.execute(text(migration.BACKFILL))

    assert await _versions(session, own) == [
        ("create", f"skills/{workspace}/packages/{'d' * 64}/", "d" * 64)
    ]
    assert await _versions(session, installed) == [
        ("install", f"skills/catalog/{'e' * 64}/", "e" * 64)
    ]
    catalog_version = (
        await session.execute(
            text("SELECT catalog_version FROM skill_versions WHERE skill_id = :id"),
            {"id": installed},
        )
    ).scalar_one()
    assert catalog_version == OLD_TREE
    assert await _versions(session, copy) == []


@pytest.fixture
async def committed():
    """Sessions on their own connections that really commit, as two requests would."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    workspace = f"ws-{uuid4()}"
    yield maker, workspace
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM skills WHERE workspace_id = :w"), {"w": workspace}
        )
    await engine.dispose()


async def _legacy_copy(maker, workspace: str, s3) -> str:
    async with maker() as setup:
        skill_id = await _skill_row(setup, workspace)
        await setup.execute(
            text("UPDATE skills SET s3_path = :p WHERE id = :id"),
            {"p": f"skills/{workspace}/{skill_id}/", "id": skill_id},
        )
        await setup.commit()
    s3.objects[f"skills/{workspace}/{skill_id}/SKILL.md"] = b"# Legacy"
    return skill_id


async def _history(maker, skill_id: str) -> tuple[str, list[tuple[str, str]]]:
    async with maker() as check:
        pointer = (
            await check.execute(text("SELECT s3_path FROM skills WHERE id = :id"), {"id": skill_id})
        ).scalar_one()
        rows = await check.execute(
            text("SELECT reason, s3_path FROM skill_versions WHERE skill_id = :id ORDER BY created_at, id"),
            {"id": skill_id},
        )
        return pointer, [tuple(r) for r in rows.all()]


async def test_a_stale_read_of_a_legacy_skill_does_not_move_it_back_over_an_edit(committed):
    maker, workspace = committed
    storage, _s3 = fake_storage()
    skill_id = await _legacy_copy(maker, workspace, _s3)
    with workspace_scope(workspace):
        async with maker() as reader_session, maker() as editor_session:
            # A run's config loaded the skill while it was still at its copy...
            reader = _service(reader_session, workspace, storage)
            stale = await reader._get_repository().get_by_id(skill_id)
            # ...then the user edited it in another request...
            editor = _service(editor_session, workspace, storage)
            await editor.set_content(skill_id, "# Edited")
            # ...and only then did the run read its body.
            body = await reader.read_skill_md(stale)

    edited = _own(workspace, {"SKILL.md": b"# Edited"})
    pointer, history = await _history(maker, skill_id)
    assert body == "# Edited"
    assert pointer == edited
    assert history == [("migrate", _own(workspace, {"SKILL.md": b"# Legacy"})), ("edit", edited)]


async def test_concurrent_edits_leave_the_pointer_where_the_history_ends(committed):
    import asyncio

    maker, workspace = committed
    storage, s3 = fake_storage()
    skill_id = await _legacy_copy(maker, workspace, s3)

    async def edit(body: str) -> None:
        with workspace_scope(workspace):
            async with maker() as session:
                await _service(session, workspace, storage).set_content(skill_id, body)

    await asyncio.gather(*(edit(f"# Edit {n}") for n in range(4)))

    pointer, history = await _history(maker, skill_id)
    assert history[0][0] == "migrate"
    assert [reason for reason, _ in history[1:]] == ["edit"] * 4
    assert pointer == history[-1][1]
    assert len({path for _, path in history}) == len(history)


async def _copy_row(engine, workspace: str) -> tuple[str, str]:
    skill_id = str(uuid4())
    own = f"skills/{workspace}/{skill_id}/"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO skills (id, name, slug, source_type, s3_path, workspace_id, "
                "created_by, network_scope, created_at, updated_at) VALUES (:id, 'pdf', :slug, "
                "'github', :p, :w, 'u1', 'private', now(), now())"
            ),
            {"id": skill_id, "slug": f"pdf-{skill_id[:8]}", "p": own, "w": workspace},
        )
    return skill_id, own


async def _cleanup(engine, skill_id: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM skills WHERE id = :id"), {"id": skill_id})


@pytest.mark.parametrize("autocommit", [False, True])
async def test_an_edit_committed_between_a_movers_read_and_its_move_wins(autocommit):
    from agentarea_agents.infrastructure.skill_repository import (
        SkillPackageMovedError,
        SkillRepository,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(TEST_DATABASE_URL)
    mover_engine = engine.execution_options(isolation_level="AUTOCOMMIT") if autocommit else engine
    workspace = f"ws-{uuid4()}"
    skill_id, own = await _copy_row(engine, workspace)
    edited = f"skills/{workspace}/packages/{'e' * 64}/"
    try:
        with workspace_scope(workspace):
            maker = async_sessionmaker(mover_engine, class_=AsyncSession, expire_on_commit=False)
            async with maker() as session:
                repo = SkillRepository(session, UserContext(user_id="u1", workspace_id=workspace))
                assert (await repo.get_by_id(skill_id)).s3_path == own
                async with engine.begin() as conn:
                    await conn.execute(
                        text("UPDATE skills SET s3_path = :p WHERE id = :id"),
                        {"p": edited, "id": skill_id},
                    )
                with pytest.raises(SkillPackageMovedError) as lost:
                    await repo.set_package(
                        skill_id, f"skills/{workspace}/packages/{'m' * 64}/", reason="migrate", expect=own
                    )
        assert lost.value.current == edited
        async with engine.connect() as conn:
            pointer = (
                await conn.execute(text("SELECT s3_path FROM skills WHERE id = :id"), {"id": skill_id})
            ).scalar_one()
            versions = (
                await conn.execute(
                    text("SELECT count(*) FROM skill_versions WHERE skill_id = :id"), {"id": skill_id}
                )
            ).scalar_one()
        assert (pointer, versions) == (edited, 0)
    finally:
        await _cleanup(engine, skill_id)
        await engine.dispose()


async def test_an_edit_landing_just_after_an_autocommit_move_is_not_reverted():
    # The probe of the review: the edit commits while the mover is between its
    # pointer move and its history row. The move is one statement, so the edit
    # comes after it and stands.
    import asyncio

    from agentarea_agents.infrastructure.skill_repository import SkillRepository
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(TEST_DATABASE_URL)
    workspace = f"ws-{uuid4()}"
    skill_id, own = await _copy_row(engine, workspace)
    edited = f"skills/{workspace}/packages/{'e' * 64}/"
    try:
        with workspace_scope(workspace):
            maker = async_sessionmaker(
                engine.execution_options(isolation_level="AUTOCOMMIT"),
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with maker() as session:
                repo = SkillRepository(session, UserContext(user_id="u1", workspace_id=workspace))
                original = repo.latest_version

                async def edit_in_the_window(sid):
                    async def edit():
                        async with engine.begin() as conn:
                            await conn.execute(
                                text("UPDATE skills SET s3_path = :p WHERE id = :id"),
                                {"p": edited, "id": skill_id},
                            )

                    await asyncio.wait_for(edit(), 5)
                    return await original(sid)

                repo.latest_version = edit_in_the_window
                await repo.set_package(
                    skill_id, f"skills/{workspace}/packages/{'m' * 64}/", reason="migrate", expect=own
                )
        async with engine.connect() as conn:
            pointer = (
                await conn.execute(text("SELECT s3_path FROM skills WHERE id = :id"), {"id": skill_id})
            ).scalar_one()
        assert pointer == edited
    finally:
        await _cleanup(engine, skill_id)
        await engine.dispose()


async def test_a_read_session_reads_a_legacy_copy_without_moving_it():
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(TEST_DATABASE_URL)
    workspace = f"ws-{uuid4()}"
    skill_id, own = await _copy_row(engine, workspace)
    storage, s3 = fake_storage()
    s3.objects[f"{own}SKILL.md"] = b"# Legacy"
    try:
        with workspace_scope(workspace):
            maker = async_sessionmaker(
                engine.execution_options(isolation_level="AUTOCOMMIT"),
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with maker() as session:
                svc = _service(session, workspace, storage)
                skill = await svc.get(skill_id)
                assert await svc.read_skill_md(skill) == "# Legacy"
                assert [f.path for f in await svc.get_skill_files(skill_id)] == ["SKILL.md"]
        async with engine.connect() as conn:
            pointer = (
                await conn.execute(text("SELECT s3_path FROM skills WHERE id = :id"), {"id": skill_id})
            ).scalar_one()
            versions = (
                await conn.execute(
                    text("SELECT count(*) FROM skill_versions WHERE skill_id = :id"), {"id": skill_id}
                )
            ).scalar_one()
        assert (pointer, versions) == (own, 0)
        assert not any(key.startswith(f"skills/{workspace}/packages/") for key in s3.objects)
    finally:
        await _cleanup(engine, skill_id)
        await engine.dispose()
