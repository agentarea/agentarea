"""The one way to a skill's files (ADR-0044: no skill body in the database).

Every skill body is a package in object storage. A tenant skill points at its
package by ``s3_path``; a catalog item's package is built from what the index
carries (a GitHub pointer, an inline body, or a legacy package) and stored once
under the digest of its files, when its registry syncs if the registry
mirrors, else on first use. A workspace registry's packages stay in that
workspace's area. Catalog packages are immutable, so their files
are cached in-process by ``s3_path`` and never invalidated.

A tenant row that still holds its body in ``skills.content`` (written before
packages) is moved into a package the first time it is read: the package is
written, ``s3_path`` set and ``content`` cleared. A row with both had its
package imported and its body edited, which wrote only the row; the edit wins
and goes into the workspace's own copy of the package. That is a one-way
migration step, logged each time; ``agentarea-api skills
move-bodies-to-packages`` does the same for every row up front.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_agents.application.skill_parser import SkillParser
from agentarea_agents.domain.skill_models import Skill
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubFolder,
    GitHubRateLimitError,
    GitHubSkillImporter,
)
from agentarea_agents.infrastructure.skill_repository import (
    SkillRepository,
    list_pre_package_skills,
)
from agentarea_agents.infrastructure.skill_storage_service import (
    SKILLS_PREFIX,
    SkillStorageService,
    catalog_area,
    is_catalog_package,
)

logger = logging.getLogger(__name__)

SKILL_MANIFEST = "SKILL.md"
CATALOG_CACHE_MAX_BYTES = 64 * 1024 * 1024

# Per process, shared by every tenant's reads, so bounded. A tree SHA names its
# content for good; a pointer without one (the index has no tree SHA yet) is
# read at the branch head, and that answer is reused for a while so previews
# do not download the folder again. An install pins the tree it read.
GITHUB_CACHE_MAX_ENTRIES = 4096
GITHUB_HEAD_TTL_SECONDS = 3600.0

_catalog_files: OrderedDict[str, dict[str, bytes]] = OrderedDict()
_catalog_bytes = 0
_github_trees: OrderedDict[tuple[str | None, str], str] = OrderedDict()
_github_heads: OrderedDict[
    tuple[str | None, str, str, str | None], tuple[float, CatalogPackage]
] = OrderedDict()


def _remember(cache: OrderedDict, key: Any, value: Any) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > GITHUB_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


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


def legacy_catalog_s3_path(spec: dict[str, Any] | None, workspace_id: str | None) -> str | None:
    """A catalog item's legacy ``spec.s3_path``, if it lies where its registry stores.

    A workspace registry's item reads only that workspace's area; a platform
    item the shared catalog area or the platform workspace's. Anything else,
    another tenant's prefix above all, is ``None``.
    """
    path = str((spec or {}).get("s3_path") or "")
    if not path or ".." in path.split("/") or "\\" in path:
        return None
    areas = (
        (f"{SKILLS_PREFIX}/{workspace_id}/",)
        if workspace_id is not None
        else (f"{catalog_area(None)}/", f"{SKILLS_PREFIX}/{PLATFORM_WORKSPACE_ID}/")
    )
    return path if path.startswith(areas) else None


def _has_pending_body(skill: Skill) -> bool:
    """A row written before packages that still holds its body in ``content``."""
    return "content" not in sa_inspect(skill).unloaded and skill.content is not None


def clear_package_cache() -> None:
    """Forget every cached catalog package (a fresh process, as tests need it)."""
    global _catalog_bytes
    _catalog_files.clear()
    _github_trees.clear()
    _github_heads.clear()
    _catalog_bytes = 0


class FolderSource(Protocol):
    async def download_folder(
        self, repo: str, path: str, *, ref: str | None, tree_sha: str | None
    ) -> GitHubFolder: ...


@dataclass(frozen=True)
class CatalogPackage:
    """Where a catalog item's package was stored, and the source it was read from.

    ``tree_sha`` is the GitHub folder's tree the package was built from, the
    version an install pins; ``None`` for content that did not come from GitHub.
    """

    s3_path: str
    source_url: str | None
    tree_sha: str | None = None


class SkillPackages:
    """Reads and stores skill packages; see the module docstring."""

    def __init__(
        self,
        storage: SkillStorageService,
        github_importer: FolderSource,
        repository: SkillRepository | None,
    ):
        self._storage = storage
        self._github = github_importer
        self._repository = repository
        self._parser = SkillParser()

    async def read_files(self, skill: Skill, *, at: str | None = None) -> dict[str, bytes]:
        s3_path = await self._package_of(skill, at)
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

    async def read_skill_md(self, skill: Skill, *, at: str | None = None) -> str:
        """The skill's SKILL.md: what activating it hands the model.

        ``at`` reads the package a run was configured with rather than the
        skill's current one, so a run keeps the version it started on.
        """
        s3_path = await self._package_of(skill, at)
        cached = _cache_get(s3_path) if is_catalog_package(s3_path) else None
        if cached is not None:
            return self._main_file(skill, cached)
        if is_catalog_package(s3_path):
            return self._main_file(skill, await self.read_files(skill, at=s3_path))
        paths = [info.path for info in await self._storage.list_files(s3_path)]
        main = self._parser.find_main_skill_file(paths)
        if main is None:
            raise ValueError(f"Skill {skill.id} package {s3_path} has no SKILL.md at its root")
        return (await self._storage.get_file_content(s3_path, main)).decode("utf-8")

    async def _package_of(self, skill: Skill, at: str | None) -> str:
        """``at`` when it is a package this skill may be read from, else the skill's own.

        A pinned path must lie in the shared catalog area or the skill's
        workspace; a row whose body is still in the database is read from it.
        """
        if at is None or _has_pending_body(skill):
            return await self.resolve_s3_path(skill)
        workspace_id = getattr(skill, "workspace_id", None) or skill.catalog_workspace_id
        areas = [f"{catalog_area(None)}/", f"{SKILLS_PREFIX}/{PLATFORM_WORKSPACE_ID}/"]
        if workspace_id is not None:
            areas.append(f"{SKILLS_PREFIX}/{workspace_id}/")
        if ".." in at.split("/") or "\\" in at or not at.startswith(tuple(areas)):
            raise ValueError(f"Skill {skill.id} cannot be read from package {at!r}")
        return at

    async def resolve_s3_path(self, skill: Skill) -> str:
        """The package of ``skill``, storing it first when it has none yet."""
        if skill.s3_path:
            if _has_pending_body(skill):
                return await self.move_body_to_package(skill)
            return skill.s3_path
        if skill.is_catalog:
            workspace_id = skill.catalog_workspace_id
            return (
                await self.store_catalog_item(skill.catalog_spec, workspace_id=workspace_id)
            ).s3_path
        if skill.content is not None:
            return await self.move_body_to_package(skill)
        raise ValueError(f"Skill {skill.id} has neither a package nor a body")

    async def move_body_to_package(self, skill: Skill) -> str:
        """Write a pre-package row's body as its SKILL.md and stop storing it in the row.

        A row that also has a package keeps that package's other files; the
        body replaces its SKILL.md in the workspace's own copy, never in a
        shared (catalog) package. A body that is already the package's SKILL.md
        is only dropped from the row.
        """
        if self._repository is None:
            raise RuntimeError("Moving a skill body into a package needs the skill repository")
        body = (skill.content or "").encode("utf-8")
        files = {SKILL_MANIFEST: body}
        if skill.s3_path:
            files = await self._storage.read_package(skill.s3_path)
            main = self._parser.find_main_skill_file(list(files)) or SKILL_MANIFEST
            if files.get(main) == body:
                if await self._repository.update(str(skill.id), content=None) is None:
                    raise RuntimeError(f"Skill {skill.id} vanished while its body was moved")
                skill.content = None
                return skill.s3_path
            files = {**files, main: body}
        s3_path = await self._storage.store_package_files(
            str(skill.id), str(skill.workspace_id), files
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

    async def store_catalog_item(
        self, spec: dict[str, Any] | None, *, workspace_id: str | None = None
    ) -> CatalogPackage:
        """Build a catalog item's package from its index entry and store it by digest.

        A mirrored item's package was stored when its registry synced and is
        used as is. Otherwise a GitHub pointer is downloaded at its pinned
        commit (verified against its tree SHA); an inline body becomes a single
        SKILL.md; a legacy package is copied. The package must have a SKILL.md
        that parses. ``workspace_id`` is the owner of a workspace registry's
        item, whose package stays in that workspace's area.
        """
        spec = spec or {}
        mirrored = spec.get("package")
        if isinstance(mirrored, dict):
            s3_path = str(mirrored.get("s3_path") or "")
            if not (
                s3_path.startswith(f"{catalog_area(workspace_id)}/") and is_catalog_package(s3_path)
            ):
                raise ValueError(
                    f"Catalog skill's mirrored package {s3_path!r} is outside its registry's store"
                )
            pointer = spec.get("source")
            return CatalogPackage(
                s3_path,
                mirrored.get("source_url") or spec.get("source_url"),
                mirrored.get("tree_sha")
                or (pointer.get("tree_sha") if isinstance(pointer, dict) else None),
            )
        source = spec.get("source")
        if isinstance(source, dict) and source.get("type") == "github":
            return await self._store_github_source(source, workspace_id)
        if isinstance(spec.get("content"), str) and spec["content"]:
            files = {SKILL_MANIFEST: spec["content"].encode("utf-8")}
            return CatalogPackage(
                await self._store_checked(files, workspace_id), spec.get("source_url")
            )
        if spec.get("s3_path"):
            legacy = legacy_catalog_s3_path(spec, workspace_id)
            if legacy is None:
                raise ValueError(
                    f"Catalog skill's package {spec['s3_path']!r} is outside its registry's store"
                )
            files = await self._storage.read_package(legacy)
            return CatalogPackage(
                await self._store_checked(files, workspace_id), spec.get("source_url")
            )
        raise ValueError("Catalog skill carries neither a source, a body nor a package")

    async def _store_github_source(
        self, source: dict[str, Any], workspace_id: str | None
    ) -> CatalogPackage:
        repo, path = str(source["repo"]), str(source.get("path") or "").strip("/")
        tree_sha = source.get("tree_sha")
        head_key = (workspace_id, repo, path, source.get("ref"))
        if not tree_sha:
            cached = _github_heads.get(head_key)
            if cached is not None and cached[0] > time.monotonic():
                return cached[1]
        if tree_sha:
            s3_path = _github_trees.get(
                (workspace_id, tree_sha)
            ) or await self._storage.get_github_tree_package(tree_sha, workspace_id=workspace_id)
            if s3_path:
                _remember(_github_trees, (workspace_id, tree_sha), s3_path)
                ref = source.get("ref")
                return CatalogPackage(
                    s3_path, _github_url(repo, path, ref) if ref else None, tree_sha
                )
        folder = await self._github.download_folder(
            repo, path, ref=source.get("ref"), tree_sha=tree_sha
        )
        s3_path = await self._store_checked(folder.files, workspace_id)
        await self._storage.put_github_tree_package(
            folder.tree_sha, s3_path, workspace_id=workspace_id
        )
        _remember(_github_trees, (workspace_id, folder.tree_sha), s3_path)
        package = CatalogPackage(s3_path, _github_url(repo, path, folder.commit), folder.tree_sha)
        if not tree_sha:
            _remember(
                _github_heads, head_key, (time.monotonic() + GITHUB_HEAD_TTL_SECONDS, package)
            )
        logger.info(
            "Fetched skill %s/%s at %s (tree %s) into %s",
            repo,
            path,
            folder.commit,
            folder.tree_sha,
            s3_path,
        )
        return package

    async def _store_checked(self, files: dict[str, bytes], workspace_id: str | None) -> str:
        self._parser.parse_content(self._main_file(None, files))
        return await self._storage.store_catalog_package(files, workspace_id=workspace_id)

    def _main_file(self, skill: Skill | None, files: dict[str, bytes]) -> str:
        main = self._parser.find_main_skill_file(list(files))
        if main is None:
            raise ValueError(
                self._parser.MISSING_SKILL_MESSAGE
                if skill is None
                else f"Skill {skill.id} package has no SKILL.md at its root"
            )
        return files[main].decode("utf-8")


class CatalogMirror:
    """Stores the package of every item of a mirror-mode registry as its index syncs.

    One per sync of one registry: ``workspace_id`` is the owner of a workspace
    registry (``None`` for the platform's), ``github`` reads with that
    registry's credentials. Returns what the item's spec keeps as ``package``,
    so an install needs no network. Once GitHub answers that the rate limit is
    spent it is not asked again in this sync; those items fail, and the next
    sync retries them.
    """

    def __init__(
        self, storage: SkillStorageService, github: FolderSource, *, workspace_id: str | None
    ):
        self._packages = SkillPackages(storage, _StopOnRateLimit(github), None)
        self._workspace_id = workspace_id

    async def __call__(self, spec: dict[str, Any]) -> dict[str, Any]:
        package = await self._packages.store_catalog_item(spec, workspace_id=self._workspace_id)
        stored = {"s3_path": package.s3_path, "source_url": package.source_url}
        if package.tree_sha:
            stored["tree_sha"] = package.tree_sha
        return stored


class _StopOnRateLimit:
    def __init__(self, github: FolderSource):
        self._github = github
        self._limited: str | None = None

    async def download_folder(
        self, repo: str, path: str, *, ref: str | None, tree_sha: str | None
    ) -> GitHubFolder:
        if self._limited is not None:
            raise GitHubRateLimitError(self._limited)
        try:
            return await self._github.download_folder(repo, path, ref=ref, tree_sha=tree_sha)
        except GitHubRateLimitError as e:
            self._limited = str(e)
            raise


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
        rows = await list_pre_package_skills(session)
    moved = failed = 0
    for skill_id, workspace_id in rows:
        try:
            with workspace_scope(workspace_id):
                async with session_factory() as session:
                    repository = SkillRepository(
                        session,
                        UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=workspace_id),
                    )
                    skill = await repository.get_by_id(skill_id)
                    if skill is None or skill.content is None:
                        continue
                    packages = SkillPackages(storage, GitHubSkillImporter(), repository)
                    await packages.move_body_to_package(skill)
                    moved += 1
        except Exception:
            logger.exception("Failed to move the body of skill %s into its package", skill_id)
            failed += 1
    return moved, failed
