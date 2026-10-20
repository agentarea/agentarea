"""Skills whose SKILL.md is an old community index's stub, refreshed from GitHub (ADR-0044).

Before packages existed, an install from a community shard copied the shard's
stub into the skill: a pointer to the original SKILL.md, not the skill. Its
catalog item may since have left the catalog, so the repin cannot reach it,
but the stub still names where the original lives. The refresh reads that
folder at its default branch's head, as a GitHub import would, and points the
skill at it, keeping its id, slug, name and agents.
"""

from __future__ import annotations

import logging
import posixpath
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Literal

from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_agents.application.skill_parser import SkillParser
from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.domain.skill_models import Skill, SkillSourceType
from agentarea_agents.infrastructure.catalog_skill_repository import CatalogSkillRepository
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubNotFoundError,
    GitHubSkillImporter,
)
from agentarea_agents.infrastructure.skill_repository import (
    SkillRepository,
    list_workspace_skills,
)
from agentarea_agents.infrastructure.skill_storage_service import SkillStorageService

logger = logging.getLogger(__name__)

STUB_MARKER = (
    "Imported system skill metadata. The original SKILL.md should be reviewed before execution."
)
_STUB_FIELDS = ("Source", "Repository", "Path")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class StubSource:
    """Where a stub says the original SKILL.md is."""

    source_url: str
    repo: str
    path: str

    @property
    def folder(self) -> str:
        path = self.path.strip("/")
        return posixpath.dirname(path) if posixpath.basename(path).lower() == "skill.md" else path


@dataclass
class StubRefreshResult:
    """What refreshing one stub skill did."""

    skill_id: str
    name: str
    status: Literal["refreshed", "would_refresh", "not_found", "refused", "error"]
    source_url: str | None = None
    commit: str | None = None
    detail: str | None = None


def parse_stub(text: str) -> StubSource | None:
    """The original a stub points at; ``None`` unless ``text`` carries the stub's
    exact marker line followed by its Source, Repository and Path lines.
    """
    lines = [line.strip() for line in text.splitlines()]
    if STUB_MARKER not in lines:
        return None
    fields: dict[str, str] = {}
    for line in lines[lines.index(STUB_MARKER) + 1 :]:
        key, sep, value = line.partition(": ")
        if sep and key in _STUB_FIELDS and key not in fields:
            fields[key] = value.strip()
    if not all(fields.get(key) for key in _STUB_FIELDS):
        return None
    return StubSource(fields["Source"], fields["Repository"], fields["Path"])


async def _stored_skill_md(storage: SkillStorageService, skill: Skill) -> str:
    """The SKILL.md a skill holds, read where it lies: reading moves no pointer."""
    if skill.content is not None:
        return skill.content
    if not skill.s3_path:
        raise ValueError(f"Skill {skill.id} has neither a package nor a body")
    main = SkillParser().find_main_skill_file(
        [info.path for info in await storage.list_files(skill.s3_path)]
    )
    if main is None:
        raise ValueError(f"Skill {skill.id} package {skill.s3_path} has no SKILL.md at its root")
    return (await storage.get_file_content(skill.s3_path, main)).decode("utf-8")


async def _github_source(service: SkillService, skill: Skill, stub: StubSource) -> tuple[str, str]:
    """``(repo, folder)`` from the stub, else from its catalog item's GitHub source."""
    if _REPO.fullmatch(stub.repo):
        return stub.repo, stub.folder
    if skill.registry_item_id is not None:
        item = await CatalogSkillRepository(
            service.repository_factory.session, service.user_context
        ).get_item(str(skill.registry_item_id))
        source = (item.spec if item else {}).get("source")
        if isinstance(source, dict) and source.get("type") == "github" and source.get("repo"):
            return str(source["repo"]), str(source.get("path") or "").strip("/")
    raise ValueError(f"The stub names no GitHub repository: {stub.repo!r}")


async def refresh_stub(
    service: SkillService, skill: Skill, stub: StubSource, *, dry_run: bool = False
) -> StubRefreshResult:
    """Point ``skill`` at the folder its stub names, read at the default branch's head.

    The install policy decides as for a GitHub import into the skill's
    workspace. The folder is stored as an immutable package in the
    workspace's packages and the skill pointed at it by compare-and-set,
    recorded in its history as a ``refresh`` at the source commit; the stub
    it held is recorded first (``migrate``), so a rollback reaches it. The
    skill is a GitHub import from then on, no catalog install: an update
    from a catalog item never replaces it. Its name stays what the
    workspace sees; a different name in the original's frontmatter is
    reported, its description taken.
    """
    name = skill.name
    repo, folder = await _github_source(service, skill, stub)
    where = f"{repo}/{folder}" if folder else repo
    try:
        await service.require_github_import_allowed()
    except CatalogInstallRefusedError as e:
        return StubRefreshResult(str(skill.id), name, "refused", detail=str(e))
    if dry_run:
        return StubRefreshResult(str(skill.id), name, "would_refresh", detail=where)
    try:
        fetched = await service.github_importer.download_folder(
            repo, folder, ref=None, tree_sha=None
        )
    except GitHubNotFoundError as e:
        return StubRefreshResult(str(skill.id), name, "not_found", detail=str(e))

    parser = SkillParser()
    main = parser.find_main_skill_file(list(fetched.files))
    if main is None:
        raise ValueError(f"{where} at {fetched.commit}: {parser.MISSING_SKILL_MESSAGE}")
    metadata = parser.parse_content(fetched.files[main].decode("utf-8")).metadata
    s3_path = await service.storage_service.store_workspace_package(
        fetched.files, str(skill.workspace_id)
    )
    source_url = f"https://github.com/{repo}/tree/{fetched.commit}" + (
        f"/{folder}" if folder else ""
    )
    changes: dict[str, Any] = {
        "registry_item_id": None,
        "source_url": source_url,
        "source_type": SkillSourceType.GITHUB.value,
    }
    notes: list[str] = []
    if metadata.name != name:
        notes.append(f"its SKILL.md names it {metadata.name!r}; the name is kept")
    if metadata.description and metadata.description != skill.description:
        changes["description"] = metadata.description
        notes.append("description taken from its SKILL.md")
    stub_package = await service.packages.resolve_s3_path(skill)
    repository = service.repository_factory.create_repository(SkillRepository)
    refreshed = await repository.set_package(
        str(skill.id),
        s3_path,
        reason="refresh",
        catalog_version=fetched.commit,
        expect=stub_package,
        **changes,
    )
    if refreshed is None:
        raise RuntimeError(f"Skill {skill.id} vanished while it was refreshed")
    logger.info("Refreshed stub skill %s from %s (%s)", skill.id, source_url, s3_path)
    return StubRefreshResult(
        str(skill.id),
        name,
        "refreshed",
        source_url=source_url,
        commit=fetched.commit,
        detail="; ".join(notes) or None,
    )


async def refresh_all_stub_installs(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    storage: SkillStorageService,
    *,
    dry_run: bool = False,
    github: GitHubSkillImporter | None = None,
) -> list[tuple[str, StubRefreshResult]]:
    """Refresh every stub skill outside the platform workspace; ``(workspace, result)`` each.

    A skill whose SKILL.md is not a stub is not reported. Each skill is read
    and refreshed in its own session under its own workspace, so one error
    (logged, reported ``error``) leaves the rest to go on and the row as it was.
    """
    importer = github or GitHubSkillImporter()
    async with session_factory() as session:
        rows = await list_workspace_skills(session)
    results: list[tuple[str, StubRefreshResult]] = []
    for skill_id, workspace_id in rows:
        context = UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=workspace_id)
        name = ""
        try:
            with workspace_scope(workspace_id):
                async with session_factory() as session:
                    service = SkillService(
                        RepositoryFactory(session, context),
                        context,
                        storage_service=storage,
                        github_importer=importer,
                    )
                    skill = await service.get(skill_id)
                    if skill is None:
                        continue
                    name = skill.name
                    stub = parse_stub(await _stored_skill_md(storage, skill))
                    if stub is None:
                        continue
                    result = await refresh_stub(service, skill, stub, dry_run=dry_run)
                    await session.commit()
        except Exception as exc:
            logger.exception(
                "Failed to refresh stub skill %s of workspace %s", skill_id, workspace_id
            )
            result = StubRefreshResult(str(skill_id), name, "error", detail=str(exc))
        results.append((workspace_id, result))
    return results
