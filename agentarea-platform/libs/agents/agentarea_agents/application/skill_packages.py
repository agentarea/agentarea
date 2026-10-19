"""The one way to a skill's files (ADR-0044: no skill body in the database).

Every skill body is a package in object storage. A tenant skill points at its
package by ``s3_path``; a catalog item's package is built from what the index
carries (a GitHub pointer, an inline body, or a legacy package) and stored once
under the digest of its files. Catalog packages are immutable, so their files
are cached in-process by ``s3_path`` and never invalidated.

A tenant row that still holds its body in ``skills.content`` (written before
packages) is moved into a package the first time it is read: the package is
written, ``s3_path`` set and ``content`` cleared. That is a one-way migration
step, logged each time; ``agentarea-api skills move-bodies-to-packages`` does
the same for every row up front.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_agents.application.skill_parser import SkillParser
from agentarea_agents.domain.skill_models import Skill
from agentarea_agents.infrastructure.github_skill_importer import GitHubSkillImporter
from agentarea_agents.infrastructure.skill_repository import SkillRepository
from agentarea_agents.infrastructure.skill_storage_service import (
    SkillStorageService,
    is_catalog_package,
)

logger = logging.getLogger(__name__)

SKILL_MANIFEST = "SKILL.md"
CATALOG_CACHE_MAX_BYTES = 64 * 1024 * 1024

_catalog_files: OrderedDict[str, dict[str, bytes]] = OrderedDict()
_catalog_bytes = 0
_github_trees: dict[str, str] = {}


def _cache_get(s3_path: str) -> dict[str, bytes] | None:
    files = _catalog_files.get(s3_path)
    if files is not None:
        _catalog_files.move_to_end(s3_path)
    return files


def _cache_put(s3_path: str, files: dict[str, bytes]) -> None:
    global _catalog_bytes
    size = sum(len(data) for data in files.values())
    if size > CATALOG_CACHE_MAX_BYTES or s3_path in _catalog_files:
        return
    _catalog_files[s3_path] = files
    _catalog_bytes += size
    while _catalog_bytes > CATALOG_CACHE_MAX_BYTES:
        _, evicted = _catalog_files.popitem(last=False)
        _catalog_bytes -= sum(len(data) for data in evicted.values())


def clear_package_cache() -> None:
    """Forget every cached catalog package (a fresh process, as tests need it)."""
    global _catalog_bytes
    _catalog_files.clear()
    _github_trees.clear()
    _catalog_bytes = 0


@dataclass(frozen=True)
class CatalogPackage:
    """Where a catalog item's package was stored, and the source it was read from."""

    s3_path: str
    source_url: str | None


class SkillPackages:
    """Reads and stores skill packages; see the module docstring."""

    def __init__(
        self,
        storage: SkillStorageService,
        github_importer: GitHubSkillImporter,
        repository: SkillRepository | None,
    ):
        self._storage = storage
        self._github = github_importer
        self._repository = repository
        self._parser = SkillParser()

    async def read_files(self, skill: Skill) -> dict[str, bytes]:
        s3_path = await self.resolve_s3_path(skill)
        if not is_catalog_package(s3_path):
            return await self._storage.read_package(s3_path)
        files = _cache_get(s3_path)
        if files is None:
            files = await self._storage.read_package(s3_path)
            _cache_put(s3_path, files)
        return files

    async def list_paths(self, skill: Skill) -> list[str]:
        s3_path = await self.resolve_s3_path(skill)
        cached = _cache_get(s3_path) if is_catalog_package(s3_path) else None
        if cached is not None:
            return list(cached)
        return [info.path for info in await self._storage.list_files(s3_path)]

    async def read_skill_md(self, skill: Skill) -> str:
        """The skill's SKILL.md: what activating it hands the model."""
        s3_path = await self.resolve_s3_path(skill)
        cached = _cache_get(s3_path) if is_catalog_package(s3_path) else None
        if cached is not None:
            return self._main_file(skill, cached)
        if is_catalog_package(s3_path):
            return self._main_file(skill, await self.read_files(skill))
        paths = [info.path for info in await self._storage.list_files(s3_path)]
        main = self._parser.find_main_skill_file(paths)
        if main is None:
            raise ValueError(f"Skill {skill.id} package {s3_path} has no SKILL.md at its root")
        return (await self._storage.get_file_content(s3_path, main)).decode("utf-8")

    async def resolve_s3_path(self, skill: Skill) -> str:
        """The package of ``skill``, storing it first when it has none yet."""
        if skill.s3_path:
            return skill.s3_path
        if skill.is_catalog:
            return (await self.store_catalog_item(skill.catalog_spec)).s3_path
        if skill.content is not None:
            return await self.move_body_to_package(skill)
        raise ValueError(f"Skill {skill.id} has neither a package nor a body")

    async def move_body_to_package(self, skill: Skill) -> str:
        """Write a pre-package row's body as its SKILL.md and stop storing it in the row."""
        if self._repository is None:
            raise RuntimeError("Moving a skill body into a package needs the skill repository")
        content = skill.content or ""
        s3_path = await self._storage.store_package_files(
            str(skill.id), str(skill.workspace_id), {SKILL_MANIFEST: content.encode("utf-8")}
        )
        updated = await self._repository.update(str(skill.id), s3_path=s3_path, content=None)
        if updated is None:
            raise RuntimeError(f"Skill {skill.id} vanished while its body was moved")
        skill.s3_path, skill.content = s3_path, None
        logger.info(
            "Moved the body of skill %s (workspace %s) into its package %s",
            skill.id,
            skill.workspace_id,
            s3_path,
        )
        return s3_path

    async def store_catalog_item(self, spec: dict[str, Any] | None) -> CatalogPackage:
        """Build a catalog item's package from its index entry and store it by digest.

        A GitHub pointer is downloaded at its pinned commit (verified against
        its tree SHA); an inline body becomes a single SKILL.md; a legacy
        package is copied. The package must have a SKILL.md that parses.
        """
        spec = spec or {}
        source = spec.get("source")
        if isinstance(source, dict) and source.get("type") == "github":
            return await self._store_github_source(source)
        if isinstance(spec.get("content"), str) and spec["content"]:
            files = {SKILL_MANIFEST: spec["content"].encode("utf-8")}
            return CatalogPackage(await self._store_checked(files), spec.get("source_url"))
        if spec.get("s3_path"):
            files = await self._storage.read_package(spec["s3_path"])
            return CatalogPackage(await self._store_checked(files), spec.get("source_url"))
        raise ValueError("Catalog skill carries neither a source, a body nor a package")

    async def _store_github_source(self, source: dict[str, Any]) -> CatalogPackage:
        repo, path = str(source["repo"]), str(source.get("path") or "").strip("/")
        tree_sha = source.get("tree_sha")
        if tree_sha:
            s3_path = _github_trees.get(tree_sha) or await self._storage.get_github_tree_package(
                tree_sha
            )
            if s3_path:
                _github_trees[tree_sha] = s3_path
                ref = source.get("ref")
                return CatalogPackage(s3_path, _github_url(repo, path, ref) if ref else None)
        folder = await self._github.download_folder(
            repo, path, ref=source.get("ref"), tree_sha=tree_sha
        )
        s3_path = await self._store_checked(folder.files)
        await self._storage.put_github_tree_package(folder.tree_sha, s3_path)
        _github_trees[folder.tree_sha] = s3_path
        logger.info(
            "Fetched skill %s/%s at %s (tree %s) into %s",
            repo,
            path,
            folder.commit,
            folder.tree_sha,
            s3_path,
        )
        return CatalogPackage(s3_path, _github_url(repo, path, folder.commit))

    async def _store_checked(self, files: dict[str, bytes]) -> str:
        self._parser.parse_content(self._main_file(None, files))
        return await self._storage.store_catalog_package(files)

    def _main_file(self, skill: Skill | None, files: dict[str, bytes]) -> str:
        main = self._parser.find_main_skill_file(list(files))
        if main is None:
            raise ValueError(
                self._parser.MISSING_SKILL_MESSAGE
                if skill is None
                else f"Skill {skill.id} package has no SKILL.md at its root"
            )
        return files[main].decode("utf-8")


def _github_url(repo: str, path: str, ref: str) -> str:
    return f"https://github.com/{repo}/tree/{ref}" + (f"/{path}" if path else "")


async def move_all_bodies_to_packages(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    storage: SkillStorageService,
) -> tuple[int, int]:
    """Move every pre-package skill body into its package; ``(moved, failed)``.

    Each row is moved in its own session under its own workspace, so one
    failure (logged) leaves the rest to move and the row as it was.
    """
    from agentarea_common.auth.context import UserContext
    from agentarea_common.base.tenant_scope import workspace_scope
    from agentarea_common.constants import PLATFORM_PRINCIPAL_ID

    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, workspace_id FROM skills "
                    "WHERE content IS NOT NULL AND s3_path IS NULL ORDER BY workspace_id, id"
                )
            )
        ).all()
    moved = failed = 0
    for row in rows:
        try:
            with workspace_scope(row.workspace_id):
                async with session_factory() as session:
                    repository = SkillRepository(
                        session,
                        UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=row.workspace_id),
                    )
                    skill = await repository.get_by_id(row.id)
                    if skill is None or skill.s3_path or skill.content is None:
                        continue
                    packages = SkillPackages(storage, GitHubSkillImporter(), repository)
                    await packages.move_body_to_package(skill)
                    moved += 1
        except Exception:
            logger.exception("Failed to move the body of skill %s into its package", row.id)
            failed += 1
    return moved, failed
