"""Skill service for managing skills."""

from __future__ import annotations

import logging
import posixpath
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Literal
from uuid import UUID

from agentarea_common.audit import audited
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.constants import GITHUB_IMPORT_REGISTRY_ID, GITHUB_IMPORT_TRUST
from agentarea_common.exceptions.errors import NotFoundError
from agentarea_common.utils.slug import generate_slug
from agentarea_governance.application.catalog_install import (
    CatalogInstallGuard,
    CatalogInstallRefusedError,
)
from agentarea_governance.domain.rules import decide_catalog_install
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_agents.application.skill_packages import (
    SKILL_MANIFEST,
    CatalogPackage,
    SkillPackages,
    is_own_copy,
    legacy_catalog_s3_path,
)
from agentarea_agents.application.skill_parser import SkillParser
from agentarea_agents.application.skill_stub import bare_stub
from agentarea_agents.domain.skill_models import Skill, SkillMember, SkillSourceType, SkillVersion
from agentarea_agents.infrastructure.catalog_skill_repository import (
    CatalogSkillItem,
    CatalogSkillRepository,
    CatalogSkillSummary,
)
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubSkillImporter,
    GitHubSourceGoneError,
    extract_skill_package,
)
from agentarea_agents.infrastructure.skill_repository import SkillRepository
from agentarea_agents.infrastructure.skill_storage_service import (
    SkillStorageService,
    is_catalog_package,
    is_workspace_package,
)
from agentarea_agents.schemas.skills_dto import (
    SkillCreateFromContent,
    SkillEditMetadata,
    SkillImportFromGithub,
)

logger = logging.getLogger(__name__)

# ``skills.name`` is String(255); a longer name read out of SKILL.md is refused
# before the insert rather than failing it.
MAX_SKILL_NAME_LENGTH = 255


def _checked_skill_name(name: str) -> str:
    """Return ``name`` if it fits the skills table, else raise ``ValueError``."""
    if not name.strip():
        raise ValueError("Skill name cannot be empty")
    if len(name) > MAX_SKILL_NAME_LENGTH:
        raise ValueError(
            f"Skill name is {len(name)} characters; the limit is {MAX_SKILL_NAME_LENGTH}. "
            "Shorten the 'name' in the SKILL.md frontmatter (or its first heading), "
            "or pass a shorter name."
        )
    return name


class SkillCustomizedError(Exception):
    """The workspace edited this installed skill; an update would discard the edit."""


class SkillNotFromCatalogError(ValueError):
    """The skill was not installed from a catalog item that still exists."""


class SkillVersionNotFoundError(NotFoundError):
    """No such version in this skill's history."""


@dataclass
class SkillUpdateResult:
    """What updating one installed skill to its catalog item's current version did."""

    skill_id: str
    name: str
    status: Literal["updated", "up_to_date", "customized", "failed"]
    skill: Skill | None = None
    error: str | None = None


@dataclass
class SkillRepinResult:
    """What re-installing one pre-package catalog install from its item did."""

    skill_id: str
    name: str
    status: Literal[
        "repinned",
        "would_repin",
        "pinned",
        "edited",
        "unverified",
        "gone",
        "refused",
        "not_installed",
        "failed",
    ]
    skill: Skill | None = None
    error: str | None = None


@dataclass
class SkillFileInfo:
    """Information about a file in a skill package."""

    path: str
    size: int
    url: str | None = None  # Presigned URL if requested


def _project_catalog_skill(item: CatalogSkillItem) -> Skill:
    """Project a catalog skill item into a transient, read-only ``Skill``.

    The projected skill is NOT persisted. Its ``id`` is the catalog item's id so
    the read/edit paths can resolve it back to the registry item. The catalog
    metadata (``is_catalog``, ``registry_item_id``, ``update_available``) is
    attached as plain attributes for the API layer to surface.

    The projection carries no body: ``catalog_spec`` keeps the item's spec,
    and the package accessor builds (and stores) the package from it when
    something reads the body.
    """
    spec = item.spec or {}

    skill = Skill(
        id=UUID(item.id),
        name=item.name,
        slug=generate_slug(item.name),
        description=item.description if item.description is not None else spec.get("description"),
        source_type=spec.get("source_type") or SkillSourceType.CONTENT.value,
        source_url=spec.get("source_url"),
        s3_path=legacy_catalog_s3_path(spec, item.registry_workspace_id),
        network_scope=spec.get("network_scope") or "private",
        registry_item_id=item.id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
    # Read-only catalog projection markers consumed by the API DTO.
    skill.is_catalog = True
    skill.update_available = False
    skill.catalog_spec = spec
    skill.catalog_workspace_id = item.registry_workspace_id
    return skill


def _pinned_version(item: CatalogSkillItem, package: CatalogPackage) -> str | None:
    """The version an install of ``item`` records: the tree it fetched, when it read GitHub.

    An index pointer that names no tree SHA has the version ``latest``; the
    tree of what was fetched is what the update check compares with what the
    folder is now.
    """
    return package.tree_sha or item.version


def is_customized(skill: Skill) -> bool:
    """An installed catalog skill whose files the workspace has edited.

    Editing an installed skill stores the edit as a package of the workspace's
    own (copy-on-write); from then on an update would replace that edit.
    """
    return bool(getattr(skill, "registry_item_id", None)) and (
        is_workspace_package(skill.s3_path) or is_own_copy(skill)
    )


def _project_catalog_summary(row: CatalogSkillSummary) -> Skill:
    """Project a catalog list row into a transient, read-only ``Skill``.

    List rows carry metadata only: ``SkillResponse`` has no content field, so
    the body is left unset rather than read out of the catalog.
    """
    skill = Skill(
        id=UUID(row.id),
        name=row.name,
        slug=generate_slug(row.name),
        description=row.description,
        source_type=row.source_type,
        source_url=row.source_url,
        network_scope=row.network_scope,
        registry_item_id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
    skill.is_catalog = True
    skill.update_available = False
    return skill


class SkillService:
    """Service for managing skills.

    Orchestrates skill creation from various sources:
    - Raw markdown content
    - ZIP file upload
    - GitHub repository
    - Local path (for declarative import)
    """

    def __init__(
        self,
        repository_factory: RepositoryFactory,
        user_context: UserContext,
        storage_service: SkillStorageService | None = None,
        github_importer: GitHubSkillImporter | None = None,
        install_guard: CatalogInstallGuard | None = None,
    ):
        self.repository_factory = repository_factory
        self.user_context = user_context
        self._storage_service = storage_service
        self._github_importer = github_importer
        self._install_guard = install_guard
        self._parser = SkillParser()

    @property
    def install_guard(self) -> CatalogInstallGuard:
        """The policy check before a catalog item's content becomes this workspace's."""
        if self._install_guard is None:
            self._install_guard = CatalogInstallGuard(
                self.repository_factory.session, self.user_context
            )
        return self._install_guard

    async def require_github_import_allowed(self) -> None:
        """A direct GitHub import is an install from the unvetted public source."""
        await self.install_guard.require_allowed(
            registry_id=GITHUB_IMPORT_REGISTRY_ID, trust=GITHUB_IMPORT_TRUST
        )

    @property
    def storage_service(self) -> SkillStorageService:
        """Lazy-load storage service."""
        if self._storage_service is None:
            self._storage_service = SkillStorageService()
        return self._storage_service

    @property
    def github_importer(self) -> GitHubSkillImporter:
        """Lazy-load GitHub importer."""
        if self._github_importer is None:
            self._github_importer = GitHubSkillImporter()
        return self._github_importer

    def _get_repository(self) -> SkillRepository:
        """Get skill repository from factory."""
        return self.repository_factory.create_repository(SkillRepository)

    @property
    def packages(self) -> SkillPackages:
        """The accessor every reader of a skill body goes through."""
        return SkillPackages(self.storage_service, self.github_importer, self._get_repository())

    async def read_skill_md(self, skill: Skill, *, at: str | None = None) -> str:
        return await self.packages.read_skill_md(skill, at=at)

    async def read_files(self, skill: Skill, *, at: str | None = None) -> dict[str, bytes]:
        return await self.packages.read_files(skill, at=at)

    def _get_catalog_repository(self) -> CatalogSkillRepository:
        """Get the read-only catalog (registry_items) repository for skills."""
        return CatalogSkillRepository(
            session=self.repository_factory.session,
            user_context=self.user_context,
        )

    async def _resolve_unique_slug(self, name: str) -> str:
        """Generate a workspace-unique slug from ``name``.

        Derived once at creation and never re-derived on rename. Collisions
        within the workspace are disambiguated with ``-2``, ``-3``, … suffixes.
        """
        repo = self._get_repository()
        base = generate_slug(name)
        if await repo.get_by_slug(base) is None:
            return base
        for suffix in range(2, 1000):
            candidate = f"{base}-{suffix}"
            if await repo.get_by_slug(candidate) is None:
                return candidate
        raise ValueError(f"Exhausted collision suffixes (-2..-999) for slug base '{base}'")

    async def _create_with_package(
        self,
        store: Callable[[str], Awaitable[str]],
        **create_kwargs: Any,
    ) -> Skill:
        """Create a skill row, store its package, and point the row at it.

        The caller has already validated the package, so a failure here is the
        store or the database, and the row is removed. A package stored before
        the failure stays: it is keyed by its digest, so another skill may
        hold the same one.
        """
        repo = self._get_repository()
        skill = await repo.create(
            slug=await self._resolve_unique_slug(create_kwargs["name"]),
            s3_path=None,  # Set once the package is stored
            **create_kwargs,
        )
        skill_id = str(skill.id)
        try:
            s3_path = await store(skill_id)
            updated = await repo.set_package(skill_id, s3_path, reason="create")
            if updated is None:
                raise RuntimeError("Failed to update skill package path")
        except BaseException:
            await self._discard_failed_create(skill_id)
            raise
        return updated

    async def _discard_failed_create(self, skill_id: str) -> None:
        """Remove the row of a create that failed midway."""
        try:
            await self._get_repository().delete(skill_id)
        except Exception:
            logger.exception("Failed to remove the row of failed skill %s", skill_id)

    @audited("skill.create", resource_type="skill")
    async def create_from_content(
        self,
        payload: SkillCreateFromContent,
    ) -> Skill:
        """Create a skill from raw markdown content.

        Args:
            payload: Pydantic DTO with content + optional name/description overrides.

        Returns:
            Created Skill entity.
        """
        parsed = self._parser.parse_content(payload.content)

        # Use provided values or fall back to parsed values
        skill_name = _checked_skill_name(payload.name or parsed.metadata.name)
        skill_description = payload.description or parsed.metadata.description

        # The body is the package's one file, not a column (ADR-0044).
        async def store(_skill_id: str) -> str:
            return await self.storage_service.store_workspace_package(
                {SKILL_MANIFEST: payload.content.encode("utf-8")}, self.user_context.workspace_id
            )

        skill = await self._create_with_package(
            store,
            name=skill_name,
            description=skill_description,
            source_type=SkillSourceType.CONTENT.value,
            content=None,
            source_url=None,
        )

        logger.info(f"Created skill '{skill_name}' from content (id={skill.id})")
        return skill

    @audited("skill.create", resource_type="skill")
    async def create_from_zip(
        self,
        zip_data: bytes | BinaryIO,
        name: str | None = None,
        description: str | None = None,
    ) -> Skill:
        """Create a skill from an uploaded ZIP file.

        Args:
            zip_data: ZIP file as bytes or file-like object (binary, not in DTO).
            name: Optional name override (typically from
                :class:`SkillCreateFromArchive` / :class:`SkillCreateFromFiles`).
            description: Optional description override.

        Returns:
            Created Skill entity.

        Raises:
            ValueError: If the upload is not a ZIP archive, has no skill file,
                holds a path or size the package limits refuse, or names the
                skill with a name the skills table cannot hold. Nothing is
                stored in that case.
        """
        if isinstance(zip_data, bytes):
            import io

            zip_data = io.BytesIO(zip_data)

        # Parse and extract from ZIP
        parsed, _manifest = self._parser.extract_main_skill_from_zip(zip_data)

        # Use provided values or fall back to parsed values
        skill_name = _checked_skill_name(name or parsed.metadata.name)
        skill_description = description or parsed.metadata.description

        # Refuse the whole package before its row exists
        files = self.storage_service.files_from_zip(zip_data)

        async def store(_skill_id: str) -> str:
            return await self.storage_service.store_workspace_package(
                files, self.user_context.workspace_id
            )

        skill = await self._create_with_package(
            store,
            name=skill_name,
            description=skill_description,
            source_type=SkillSourceType.ZIP.value,
            content=None,
            source_url=None,
        )

        logger.info(f"Created skill '{skill_name}' from ZIP (id={skill.id})")
        return skill

    @audited("skill.create", resource_type="skill")
    async def create_from_github(
        self,
        payload: SkillImportFromGithub,
    ) -> Skill:
        """Create a skill from a GitHub repository.

        Args:
            payload: Pydantic DTO with github_url + optional name/description.

        Returns:
            Created Skill entity.

        Raises:
            GitHubSkillImporterError: If download fails.
            ValueError: If no skill file is found in the repository.
            CatalogInstallRefusedError: If the install policy refuses GitHub imports.
        """
        await self.require_github_import_allowed()

        # Download repository as ZIP and re-root it on the package the URL points at
        repo_info = self.github_importer.parse_github_url(payload.github_url)
        repo_zip_data = await self.github_importer.download_repo(payload.github_url)
        zip_data = extract_skill_package(repo_zip_data, package_path=repo_info.path)

        # Parse and extract from ZIP
        import io

        zip_buffer = io.BytesIO(zip_data)
        parsed, _manifest = self._parser.extract_main_skill_from_zip(zip_buffer)

        # Use provided values or fall back to parsed values
        skill_name = _checked_skill_name(payload.name or parsed.metadata.name)
        skill_description = payload.description or parsed.metadata.description

        # Refuse the whole package before its row exists
        files = self.storage_service.files_from_zip(zip_buffer)

        async def store(_skill_id: str) -> str:
            return await self.storage_service.store_workspace_package(
                files, self.user_context.workspace_id
            )

        skill = await self._create_with_package(
            store,
            name=skill_name,
            description=skill_description,
            source_type=SkillSourceType.GITHUB.value,
            content=None,
            source_url=payload.github_url,
        )

        logger.info(
            f"Created skill '{skill_name}' from GitHub: {payload.github_url} (id={skill.id})"
        )
        return skill

    @audited("skill.create", resource_type="skill")
    async def create_from_path(
        self,
        path: str,
        base_dir: str | Path | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> Skill:
        """Create a skill from a local path (directory or archive).

        Used for declarative import.

        Args:
            path: Relative or absolute path to directory or ZIP file.
            base_dir: Base directory for resolving relative paths.
            name: Optional name override.
            description: Optional description override.

        Returns:
            Created Skill entity.

        Raises:
            FileNotFoundError: If the path does not exist.
            ValueError: If no skill file is found.
        """
        # Resolve path
        if base_dir:
            full_path = Path(base_dir) / path
        else:
            full_path = Path(path)

        if not full_path.exists():
            raise FileNotFoundError(f"Path does not exist: {full_path}")

        # Handle ZIP file
        if full_path.is_file() and full_path.suffix.lower() == ".zip":
            with open(full_path, "rb") as f:
                return await self.create_from_zip(f, name=name, description=description)

        # Handle directory
        if full_path.is_dir():
            manifest = self._parser.build_manifest_from_directory(full_path)

            if not manifest.main_skill_path:
                raise ValueError(self._parser.MISSING_SKILL_MESSAGE)

            # Read and parse main skill file
            main_skill_file = full_path / manifest.main_skill_path
            content = main_skill_file.read_text(encoding="utf-8")
            parsed = self._parser.parse_content(content)

            # Use provided values or fall back to parsed values
            skill_name = _checked_skill_name(name or parsed.metadata.name)
            skill_description = description or parsed.metadata.description

            files = self.storage_service.files_from_directory(full_path)

            async def store(_skill_id: str) -> str:
                return await self.storage_service.store_workspace_package(
                    files, self.user_context.workspace_id
                )

            skill = await self._create_with_package(
                store,
                name=skill_name,
                description=skill_description,
                source_type=SkillSourceType.PATH.value,
                content=None,
                source_url=None,
            )

            logger.info(f"Created skill '{skill_name}' from path: {full_path} (id={skill.id})")
            return skill

        raise ValueError(f"Path is neither a directory nor a ZIP file: {full_path}")

    async def get(self, skill_id: UUID | str) -> Skill | None:
        """Get a skill by ID.

        Args:
            skill_id: The skill ID.

        Returns:
            Skill entity or None if not found.
        """
        repo = self._get_repository()
        return await repo.get_by_id(skill_id)

    async def get_by_name(self, name: str) -> Skill | None:
        """Get a skill by name.

        Args:
            name: The skill name.

        Returns:
            Skill entity or None if not found.
        """
        repo = self._get_repository()
        return await repo.get_by_name(name)

    async def get_by_slug(self, slug: str) -> Skill | None:
        """Get a skill by workspace-scoped slug.

        Args:
            slug: The slug.

        Returns:
            Skill entity or None if not found.
        """
        repo = self._get_repository()
        return await repo.get_by_slug(slug)

    async def _catalog_projections(self, tenant_skills: list[Skill]) -> list[Skill]:
        """Project un-forked catalog skill items as read-only ``Skill`` rows.

        A catalog item that has already been forked (a tenant ``skills`` row
        carries its ``registry_item_id``) is shadowed by that tenant copy; the
        copy is flagged ``update_available`` when the catalog version differs
        from the version recorded at fork time. Returns only the projections for
        un-forked catalog items.
        """
        catalog_items = await self._get_catalog_repository().list_items()

        forked_by_item: dict[str, Skill] = {
            str(s.registry_item_id): s
            for s in tenant_skills
            if getattr(s, "registry_item_id", None)
        }

        projections: list[Skill] = []
        for item in catalog_items:
            forked = forked_by_item.get(item.id)
            if forked is not None:
                if item.version and item.version != item.installed_version:
                    forked.update_available = True
                continue
            projections.append(_project_catalog_skill(item))
        return projections

    async def list(self, include_catalog: bool = False) -> list[Skill]:
        """List the workspace's own skills.

        Catalog (built-in) skills live in the global registry and are reached
        through search or by id -- they are NOT part of the working set, so they
        are excluded by default, mirroring ``AgentService.list``. Pass
        ``include_catalog=True`` to also project un-forked catalog items as
        read-only (ADR-003); a catalog item already forked into the workspace is
        shadowed by the tenant copy.

        Materializing the catalog is expensive enough to take the process down:
        it is one unbounded read of every ``registry_items`` row of type
        ``skills``, spec JSONB included, and turning that into objects is
        synchronous CPU work that stalls the event loop for the whole API.
        Prefer ``list_paginated``, which filters and pages in SQL.

        Returns:
            List of Skill entities.
        """
        repo = self._get_repository()
        tenant_skills = await repo.list_all()
        if not include_catalog:
            return list(tenant_skills)
        projections = await self._catalog_projections(tenant_skills)
        return [*tenant_skills, *projections]

    async def list_paginated(
        self,
        limit: int,
        offset: int = 0,
        search: str | None = None,
        source_type: str | None = None,
        network_scope: str | None = None,
        from_registry: bool | None = None,
        ids: set[str] | None = None,
        include_catalog: bool = True,
    ) -> tuple[list[Skill], int]:
        """List skills with pagination metadata, merging catalog projections.

        The merged view is tenant rows first, then read-only catalog
        projections; forked catalog items are shadowed by their tenant copy.
        Both halves are filtered and paginated in SQL — the catalog is global
        and large, so it must never be materialized per request.

        ``ids`` narrows the tenant half to what the caller may read. The
        catalog half is untouched by it: catalog items are platform data with
        no ownership tuples, and filtering them would empty Explore.
        ``include_catalog=False`` leaves the catalog half out entirely.
        """
        repo = self._get_repository()
        tenant_page, tenant_total = await repo.list_paginated(
            limit=limit,
            offset=offset,
            search=search,
            source_type=source_type,
            network_scope=network_scope,
            from_registry=from_registry,
            ids=ids,
        )
        await self.annotate_installs(tenant_page)

        # Catalog items are registry-backed by definition, so an explicit
        # "not from a registry" filter excludes the whole catalog half.
        if from_registry is False or not include_catalog:
            return tenant_page, tenant_total

        catalog_rows, catalog_total = await self._get_catalog_repository().list_page(
            limit=max(0, limit - len(tenant_page)),
            offset=max(0, offset - tenant_total),
            exclude_item_ids=await repo.list_registry_item_ids(),
            search=search,
            source_type=source_type,
            network_scope=network_scope,
        )
        page = [*tenant_page, *(_project_catalog_summary(row) for row in catalog_rows)]
        return page, tenant_total + catalog_total

    async def annotate_installs(self, skills: list[Skill]) -> None:
        """Mark installed skills on this page whose catalog item moved on, and say
        which registry each came from and whether its source still has it.
        """
        forked = {str(s.registry_item_id) for s in skills if getattr(s, "registry_item_id", None)}
        if not forked:
            return
        catalog = self._get_catalog_repository()
        versions = await catalog.versions_for(forked)
        provenance = await catalog.provenance_for(forked)
        for skill in skills:
            item_id = getattr(skill, "registry_item_id", None)
            if item_id is None:
                continue
            catalog_version, installed_version = versions.get(str(item_id), (None, None))
            if catalog_version and catalog_version != installed_version:
                skill.update_available = True
            skill.catalog_provenance = provenance.get(str(item_id))

    async def run_refusals(self, skills: list[Skill]) -> dict[str, str]:
        """Why the install policy keeps a run from each of ``skills``, by skill id.

        An install was decided once; a rule written since (denying a trust
        level or a registry) holds for the skills already installed from it.
        A run is held to the workspace's rules alone, so an agent's skills do
        not depend on who started the run. A skill imported from a GitHub URL
        is from the public source; one the workspace wrote has no registry
        and is not asked about, and neither is an install whose registry item
        is gone, since it holds its own package. One read of the provenance
        and one of the rules, whatever the number of skills.
        """
        item_ids = [
            str(skill.registry_item_id)
            for skill in skills
            if getattr(skill, "registry_item_id", None) is not None
        ]
        provenance = (
            await self._get_catalog_repository().provenance_for(item_ids) if item_ids else {}
        )
        sources: dict[str, tuple[str, str]] = {}
        for skill in skills:
            item_id = getattr(skill, "registry_item_id", None)
            if item_id is not None:
                found = provenance.get(str(item_id))
                if found is not None:
                    sources[str(skill.id)] = (found.registry_id, found.registry_trust)
            elif skill.source_type == SkillSourceType.GITHUB.value:
                sources[str(skill.id)] = (GITHUB_IMPORT_REGISTRY_ID, GITHUB_IMPORT_TRUST)
        if not sources:
            return {}
        rules = await self.install_guard.run_time_rules()
        refusals: dict[str, str] = {}
        for skill_id, (registry_id, trust) in sources.items():
            decision = decide_catalog_install(rules, registry_id=registry_id, trust=trust)
            if not decision.allowed:
                refusals[skill_id] = decision.reason
        return refusals

    async def require_runnable(self, skill: Skill) -> None:
        """Raise ``CatalogInstallRefusedError`` when a run may not use ``skill``."""
        reason = (await self.run_refusals([skill])).get(str(skill.id))
        if reason is not None:
            raise CatalogInstallRefusedError(f"Refused by policy: {reason}")

    async def get_with_catalog(self, skill_id: UUID | str, *, to_run: bool = False) -> Skill | None:
        """Get a tenant skill by id, falling back to a catalog projection.

        Returns the tenant ``skills`` row if present; otherwise projects the
        matching catalog ``registry_item`` (read-only). No DB row is created.
        A run reads the catalog item's content without installing it, so with
        ``to_run`` the install policy decides first, for an installed skill too
        (see :meth:`run_refusals`).
        """
        skill = await self.get(skill_id)
        if skill is not None:
            if to_run:
                await self.require_runnable(skill)
            return skill
        item = await self._get_catalog_repository().get_item(str(skill_id))
        if item is None:
            return None
        projection = _project_catalog_skill(item)
        if to_run:
            await self.require_runnable(projection)
        return projection

    async def _fork_catalog_skill(self, item: CatalogSkillItem) -> Skill:
        """Copy-on-write: materialize a tenant ``skills`` row from a catalog item.

        Creates a real, owned skill (workspace_id/created_by come from the
        repository's UserContext — never ``platform``), links it back to the
        catalog item via ``registry_item_id``, and records workspace-scoped
        install state for that catalog item.

        An install is a pin (ADR-0044): the item's package is built from its
        index entry (a GitHub folder at its pinned commit, verified against its
        tree SHA, or an inline body), stored once under its digest, and the
        tenant row points at it. The row stores no body. The pin recorded in
        ``registry_item_installs.installed_version`` is the item's version --
        the tree SHA for a GitHub pointer -- which the update check compares
        with the item's current one. The package is not copied: the first
        edit of a file copies it into the workspace (copy-on-write, see
        :meth:`set_content` / :meth:`replace_package_from_files`).

        Skill members are not copied here: the catalog spec carries metadata
        only, and member edits on a forked bundle go through the member API.

        Every way a catalog skill becomes the workspace's own comes through
        here, so this is where the install policy is asked.
        """
        await self.install_guard.require_allowed(
            registry_id=item.registry_id, trust=item.registry_trust
        )
        spec = item.spec or {}
        package = await self.packages.store_catalog_item(
            spec, workspace_id=item.registry_workspace_id
        )
        repo = self._get_repository()
        skill = await repo.create(
            name=item.name,
            slug=await self._resolve_unique_slug(item.name),
            description=item.description
            if item.description is not None
            else spec.get("description"),
            source_type=spec.get("source_type") or SkillSourceType.CONTENT.value,
            content=None,
            source_url=package.source_url or spec.get("source_url"),
            s3_path=package.s3_path,
            network_scope=spec.get("network_scope") or "private",
            registry_item_id=item.id,
        )
        pinned = _pinned_version(item, package)
        await self._get_catalog_repository().mark_installed(item.id, str(skill.id), pinned)
        await repo.add_version(skill, reason="install", catalog_version=pinned)
        logger.info(
            "Forked catalog skill '%s' (item=%s) into tenant skill %s",
            item.name,
            item.id,
            skill.id,
        )
        return skill

    async def install_catalog_skill(self, skill_id: UUID | str) -> Skill | None:
        """Materialize a catalog skill into the workspace.

        Idempotent: if the id is already a tenant skill, returns it. If this
        workspace has already forked the catalog item, returns that copy.
        """
        existing = await self.get(skill_id)
        if existing is not None:
            return existing

        item = await self._get_catalog_repository().get_item(str(skill_id))
        if item is None:
            return None

        forked = await self._get_repository().get_by_registry_item_id(item.id)
        if forked is not None:
            return forked

        return await self._fork_catalog_skill(item)

    async def update_from_catalog(
        self, skill_id: UUID | str, *, discard_changes: bool = False
    ) -> SkillUpdateResult:
        """Move an installed skill to its catalog item's current version.

        Raises:
            NotFoundError: No such skill in this workspace.
            SkillNotFromCatalogError: It was not installed from a catalog item,
                or that item is gone.
            SkillCustomizedError: The workspace edited it and
                ``discard_changes`` is not set.
        """
        skill = await self.get(skill_id)
        if skill is None:
            raise NotFoundError("Skill not found")
        if skill.registry_item_id is None:
            raise SkillNotFromCatalogError(f"Skill {skill.id} was not installed from a catalog")
        item = await self._get_catalog_repository().get_item(str(skill.registry_item_id))
        if item is None:
            raise SkillNotFromCatalogError(
                f"The catalog item skill {skill.id} was installed from is no longer listed"
            )
        return await self._apply_catalog_version(skill.id, skill, item, discard_changes)

    async def update_all_from_catalog(self) -> list[SkillUpdateResult]:
        """Update every installed skill whose catalog item has a newer version.

        A customized skill is reported and left alone; a skill whose update
        fails is reported with the reason and the rest still update.
        """
        installed = await self._get_repository().list_from_catalog()
        versions = await self._get_catalog_repository().versions_for(
            {str(s.registry_item_id) for s in installed}
        )
        results: list[SkillUpdateResult] = []
        for skill in installed:
            current, pinned = versions.get(str(skill.registry_item_id), (None, None))
            if not current or current == pinned:
                continue
            if is_customized(skill):
                results.append(SkillUpdateResult(str(skill.id), skill.name, "customized", skill))
                continue
            try:
                results.append(await self.update_from_catalog(skill.id))
            except Exception as exc:
                logger.warning(
                    "Updating skill %s from its catalog item failed", skill.id, exc_info=True
                )
                results.append(
                    SkillUpdateResult(str(skill.id), skill.name, "failed", error=str(exc))
                )
        return results

    @audited("skill.update", resource_type="skill", resource_id_param="skill_id")
    async def _apply_catalog_version(
        self,
        skill_id: UUID,
        skill: Skill,
        item: CatalogSkillItem,
        discard_changes: bool,
    ) -> SkillUpdateResult:
        customized = is_customized(skill)
        if customized and not discard_changes:
            raise SkillCustomizedError(
                f"Skill {skill_id} was edited in this workspace; updating it would discard "
                "the edit. Pass discard_changes to update anyway."
            )
        if not customized and item.version == item.installed_version:
            return SkillUpdateResult(str(skill_id), skill.name, "up_to_date", skill)
        updated = await self._pin_to_catalog(skill, item)
        return SkillUpdateResult(str(skill_id), updated.name, "updated", updated)

    async def _pin_to_catalog(self, skill: Skill, item: CatalogSkillItem) -> Skill:
        """Point ``skill`` at its item's current package and move the pin there.

        An edit it replaces stays in the skill's history: a pre-package copy is
        stored as a package first, so a rollback can return to it.
        """
        await self.install_guard.require_allowed(
            registry_id=item.registry_id, trust=item.registry_trust
        )
        if is_own_copy(skill):
            await self.packages.move_own_copy_to_package(skill)
        package = await self.packages.store_catalog_item(
            item.spec, workspace_id=item.registry_workspace_id
        )
        pinned = _pinned_version(item, package)
        await self._get_catalog_repository().mark_installed(item.id, str(skill.id), pinned)
        updated = await self._get_repository().set_package(
            str(skill.id),
            package.s3_path,
            reason="update",
            catalog_version=pinned,
            source_url=package.source_url or (item.spec or {}).get("source_url"),
        )
        if updated is None:
            raise NotFoundError("Skill not found")
        logger.info(
            "Pinned skill %s to catalog item %s version %s (%s)",
            skill.id,
            item.id,
            pinned,
            package.s3_path,
        )
        return updated

    async def repin_from_catalog(
        self, skill_id: UUID | str, *, dry_run: bool = False
    ) -> SkillRepinResult:
        """Re-install a catalog install made before packages existed, if nobody edited it.

        Such an install copied its item's body (the stub an index carried)
        into the row, so it reads as edited. When the body is still exactly
        what the item gave it, or the bare stub of the GitHub folder the item
        now points at, it is pinned to the item's current package in place:
        same id, same agents. An install pinned to a package that is such a
        stub moves the same way. An edited body, or one the item no longer
        carries to compare with, is left alone; a gone item is reported.

        Raises:
            NotFoundError: No such skill in this workspace.
        """
        found = await self.get(skill_id)
        if found is None:
            raise NotFoundError("Skill not found")
        skill: Skill = found

        def result(status: Any, error: str | None = None) -> SkillRepinResult:
            return SkillRepinResult(str(skill.id), skill.name, status, skill, error)

        if skill.registry_item_id is None:
            return result("not_installed")
        item = await self._get_catalog_repository().get_item(str(skill.registry_item_id))
        if is_catalog_package(skill.s3_path):
            if (
                item is None
                or item.version == item.installed_version
                or not await self._holds_the_stub_of(skill, item)
            ):
                return result("pinned")
        elif item is None:
            return result("gone", "its catalog item is no longer listed")
        else:
            as_installed = await self._holds_what_its_item_gave(skill, item)
            if as_installed is None:
                return result("unverified", "its catalog item no longer carries the body it gave")
            if not as_installed:
                return result("edited")
        if dry_run:
            return result("would_repin")
        try:
            skill = await self._pin_to_catalog(skill, item)
        except CatalogInstallRefusedError as e:
            return result("refused", str(e))
        except GitHubSourceGoneError as e:
            return result("gone", str(e))
        return result("repinned")

    async def _holds_what_its_item_gave(self, skill: Skill, item: CatalogSkillItem) -> bool | None:
        """Whether a pre-package install's body is what its item gave it; ``None``
        when the item no longer carries that body to compare with.
        """
        spec = item.spec or {}
        if skill.s3_path and skill.s3_path == spec.get("s3_path"):
            # Still reading the package it was installed with; never copied.
            return True
        body = spec.get("content")
        if not isinstance(body, str) or not body:
            return True if await self._holds_the_stub_of(skill, item) else None
        if skill.s3_path is None:
            return skill.content == body
        if not (is_own_copy(skill) or is_workspace_package(skill.s3_path)):
            return False
        files = await self.storage_service.read_package(skill.s3_path)
        return files == {SKILL_MANIFEST: body.encode("utf-8")}

    async def _holds_the_stub_of(self, skill: Skill, item: CatalogSkillItem) -> bool:
        """Whether ``skill`` holds nothing but an old index's stub of the folder ``item`` points at.

        Matched by repository and folder name: the old curated index recorded
        some folders under a parent they do not live in.
        """
        source = (item.spec or {}).get("source")
        if not isinstance(source, dict) or source.get("type") != "github":
            return False
        files = await self.storage_service.read_package(skill.s3_path) if skill.s3_path else {}
        if skill.content is not None:
            files = {**files, SKILL_MANIFEST: skill.content.encode("utf-8")}
        if list(files) != [SKILL_MANIFEST]:
            return False
        stub = bare_stub(files[SKILL_MANIFEST].decode("utf-8", errors="replace"))
        folder = str(source.get("path") or "").strip("/")
        return (
            stub is not None
            and stub.repo == source.get("repo")
            and posixpath.basename(stub.folder) == posixpath.basename(folder)
        )

    async def _resolve_for_edit(self, skill_id: UUID | str) -> Skill | None:
        """Resolve a skill id to an editable tenant row, forking if needed.

        If the id is a tenant ``skills`` row, returns it. If it resolves to a
        catalog (not-yet-materialized) skill, forks a real tenant copy
        (copy-on-write) and returns that. Returns ``None`` when the id matches
        neither.
        """
        skill = await self.get(skill_id)
        if skill is not None:
            return skill
        item = await self._get_catalog_repository().get_item(str(skill_id))
        if item is None:
            return None
        return await self._fork_catalog_skill(item)

    async def update(
        self,
        skill_id: UUID | str,
        payload: SkillEditMetadata,
    ) -> Skill | None:
        """Update a skill's metadata (name and/or description).

        Editing a catalog (built-in) skill forks a real tenant copy first
        (copy-on-write) and applies the edit to that copy.
        """
        skill = await self._resolve_for_edit(skill_id)
        if skill is None:
            return None
        return await self._update_audited(skill.id, payload)

    @audited("skill.update", resource_type="skill", resource_id_param="skill_id")
    async def _update_audited(self, skill_id: UUID, payload: SkillEditMetadata) -> Skill | None:
        repo = self._get_repository()
        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
        if not update_data:
            return await repo.get_by_id(skill_id)
        return await repo.update(str(skill_id), **update_data)

    async def set_content(
        self,
        skill_id: UUID | str,
        content: str,
    ) -> Skill | None:
        """Replace the SKILL.md content of a content-mode skill.

        Editing a catalog (built-in) skill forks a real tenant copy first
        (copy-on-write) and writes the content to that copy.
        """
        skill = await self._resolve_for_edit(skill_id)
        if skill is None:
            return None
        return await self._set_content_audited(skill.id, content)

    @audited("skill.update", resource_type="skill", resource_id_param="skill_id")
    async def _set_content_audited(self, skill_id: UUID, content: str) -> Skill | None:
        skill = await self._get_repository().get_by_id(skill_id)
        if skill is None:
            return None
        files = await self.packages.read_files(skill)
        main = self._parser.find_main_skill_file(list(files)) or SKILL_MANIFEST
        return await self._write_own_package(skill, {**files, main: content.encode("utf-8")})

    async def _write_own_package(self, skill: Skill, files: dict[str, bytes]) -> Skill:
        """Store ``files`` as a new package of the workspace's own and point the skill at it.

        No package is ever written to: an installed (catalog) package and the
        skill's earlier versions stay as they are, and the move is recorded in
        the skill's history.
        """
        previous = skill.s3_path
        new_s3_path = await self.storage_service.store_workspace_package(
            files, self.user_context.workspace_id
        )
        result = await self._get_repository().set_package(str(skill.id), new_s3_path, reason="edit")
        if result is None:
            raise RuntimeError("Failed to update skill content")
        logger.info(
            "Skill %s now at package %s (%d files, was %s)",
            skill.id,
            new_s3_path,
            len(files),
            previous,
        )
        return result

    async def list_versions(self, skill_id: UUID | str) -> list[SkillVersion]:
        """Every package the skill pointed at, oldest first.

        Raises:
            NotFoundError: No such skill in this workspace.
        """
        skill = await self.get(skill_id)
        if skill is None:
            raise NotFoundError("Skill not found")
        await self.packages.resolve_s3_path(skill)
        return await self._get_repository().list_versions(skill.id)

    @audited("skill.update", resource_type="skill", resource_id_param="skill_id")
    async def rollback(self, skill_id: UUID | str, version_id: UUID | str) -> Skill:
        """Point the skill at the package one of its earlier versions had.

        The move is itself recorded, so a rollback can be undone the same way.
        A version that was a catalog package re-pins the install to the
        version it was installed at, which the install policy is asked about
        as an install is.

        Raises:
            NotFoundError: No such skill in this workspace.
            SkillVersionNotFoundError: No such version of this skill.
        """
        skill = await self.get(skill_id)
        if skill is None:
            raise NotFoundError("Skill not found")
        repo = self._get_repository()
        version = await repo.get_version(skill.id, version_id)
        if version is None:
            raise SkillVersionNotFoundError(f"Skill {skill.id} has no version {version_id}")
        if is_catalog_package(version.s3_path) and skill.registry_item_id is not None:
            item = await self._get_catalog_repository().get_item(str(skill.registry_item_id))
            if item is not None:
                await self.install_guard.require_allowed(
                    registry_id=item.registry_id, trust=item.registry_trust
                )
                await self._get_catalog_repository().mark_installed(
                    item.id, str(skill.id), version.catalog_version
                )
        updated = await repo.set_package(
            str(skill.id),
            version.s3_path,
            reason="rollback",
            catalog_version=version.catalog_version,
        )
        if updated is None:
            raise NotFoundError("Skill not found")
        logger.info(
            "Rolled skill %s back to version %s (%s)", skill.id, version.id, version.s3_path
        )
        return updated

    async def replace_package_from_files(
        self,
        skill_id: UUID | str,
        files: dict[str, str],
    ) -> Skill:
        """Replace a package-mode skill's file tree with the given map.

        Editing a catalog (built-in) skill forks a real tenant copy first
        (copy-on-write). The audit event is recorded against the resolved
        tenant skill UUID, not the original catalog UUID.
        """
        skill = await self._resolve_for_edit(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        return await self._replace_package_audited(skill.id, skill, files)

    @audited("skill.update", resource_type="skill", resource_id_param="skill_id")
    async def _replace_package_audited(
        self,
        skill_id: UUID,
        skill: Skill,
        files: dict[str, str],
    ) -> Skill:
        if not any(k.lower() in ("skill.md", "skill.markdown") for k in files):
            raise ValueError("files must include a SKILL.md at the root")
        await self.packages.resolve_s3_path(skill)
        return await self._write_own_package(
            skill, {path: text.encode("utf-8") for path, text in files.items()}
        )

    @audited("skill.delete", resource_type="skill", resource_id_param="skill_id")
    async def delete(self, skill_id: UUID | str) -> bool:
        """Delete a skill and clean up S3 storage.

        Args:
            skill_id: The skill ID.

        Returns:
            True if deleted, False if not found.
        """
        repo = self._get_repository()

        # Get skill to check S3 path
        skill = await repo.get_by_id(skill_id)
        if not skill:
            return False

        # Only a pre-package copy belongs to this skill alone; packages are
        # keyed by digest and may be another skill's too.
        if is_own_copy(skill):
            own_prefix = str(skill.s3_path)
            try:
                await self.storage_service.delete_package(own_prefix)
            except Exception as e:
                logger.warning(
                    f"Failed to delete S3 package for skill {skill_id}: {e}", exc_info=True
                )

        # Delete from database
        await repo.delete(str(skill_id))

        logger.info(f"Deleted skill {skill_id}")
        return True

    async def get_skill_files(
        self,
        skill_id: UUID | str,
        include_urls: bool = False,
        *,
        to_run: bool = False,
    ) -> list[SkillFileInfo]:
        """Get list of files in a skill package.

        Args:
            skill_id: The skill ID.
            include_urls: If True, include presigned URLs for each file.
            to_run: Read for a run: a catalog item the install policy
                refuses is not read (see ``get_with_catalog``).

        Returns:
            List of SkillFileInfo objects.

        Raises:
            ValueError: If skill is not a multi-file package.
        """
        skill = await self.get_with_catalog(skill_id, to_run=to_run)

        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        s3_path = await self.packages.resolve_s3_path(skill)
        files = await self.storage_service.list_files(s3_path)

        result = []
        for file_info in files:
            skill_file = SkillFileInfo(
                path=file_info.path,
                size=file_info.size,
            )

            if include_urls:
                skill_file.url = await self.storage_service.get_file_url(s3_path, file_info.path)

            result.append(skill_file)

        return result

    async def get_skill_file_url(
        self,
        skill_id: UUID | str,
        path: str,
        expires_in: int = 3600,
        *,
        to_run: bool = False,
    ) -> str:
        """Get a presigned URL for a file in a skill package.

        Args:
            skill_id: The skill ID.
            path: Relative path to the file.
            expires_in: URL expiration time in seconds.
            to_run: Read for a run; see ``get_skill_files``.

        Returns:
            Presigned URL.

        Raises:
            ValueError: If skill is not found or has no S3 storage.
        """
        skill = await self.get_with_catalog(skill_id, to_run=to_run)

        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        return await self.storage_service.get_file_url(
            await self.packages.resolve_s3_path(skill),
            path,
            expires_in=expires_in,
        )

    # ------------------------------------------------------------------
    # Skill member management (skill-as-bundle / self-referential)
    # ------------------------------------------------------------------

    async def _require_skill(self, skill_id: UUID | str) -> None:
        """Resolve a bundle end in this workspace; a foreign id is not found."""
        if await self._get_repository().get_by_id(skill_id) is None:
            raise NotFoundError("Skill not found")

    async def add_member(
        self,
        parent_skill_id: UUID | str,
        child_skill_id: UUID | str,
        order: int = 0,
        is_required: bool = True,
        dependencies: list[str] | None = None,
    ) -> SkillMember:
        """Add a child skill to a parent skill, validating for cycles first.

        Args:
            parent_skill_id: The parent skill ID.
            child_skill_id: The child skill to add.
            order: Execution order hint.
            is_required: Whether this child is required.
            dependencies: IDs of other children that must run before this one.

        Returns:
            Created or updated SkillMember.

        Raises:
            NotFoundError: If the parent or child skill is not in this workspace.
            ValueError: If adding the child would create a cycle.
        """
        from uuid import UUID as _UUID

        parent_id = _UUID(str(parent_skill_id))
        child_id = _UUID(str(child_skill_id))

        repo = self._get_repository()

        if parent_id == child_id:
            raise ValueError("A skill cannot be a member of itself")
        await self._require_skill(parent_id)
        await self._require_skill(child_id)

        # Fetch existing members and simulate adding the new one for cycle detection
        existing = await repo.get_members(parent_id)
        test_members = [
            *existing,
            SkillMember(
                parent_skill_id=parent_id,
                child_skill_id=child_id,
                dependencies=dependencies or [],
            ),
        ]
        try:
            _topological_sort(test_members)
        except ValueError as exc:
            raise ValueError(f"Adding skill {child_id} would create a cycle") from exc

        return await repo.add_member(
            parent_skill_id=parent_id,
            child_skill_id=child_id,
            order=order,
            is_required=is_required,
            dependencies=dependencies,
        )

    async def remove_member(
        self,
        parent_skill_id: UUID | str,
        child_skill_id: UUID | str,
    ) -> bool:
        """Remove a child skill from a parent skill.

        Returns:
            True if removed, False if the association did not exist.
        """
        from uuid import UUID as _UUID

        repo = self._get_repository()
        await self._require_skill(parent_skill_id)
        return await repo.remove_member(
            _UUID(str(parent_skill_id)),
            _UUID(str(child_skill_id)),
        )

    async def get_members(self, parent_skill_id: UUID | str) -> list[SkillMember]:
        """Get all direct child skills of a parent skill.

        Returns:
            List of SkillMember objects ordered by 'order' field.
        """
        from uuid import UUID as _UUID

        repo = self._get_repository()
        await self._require_skill(parent_skill_id)
        return await repo.get_members(_UUID(str(parent_skill_id)))

    async def flatten(self, parent_skill_id: UUID | str) -> list[UUID]:
        """Return child skill IDs in topological execution order.

        Raises:
            ValueError: If circular dependencies are detected.
        """
        from uuid import UUID as _UUID

        repo = self._get_repository()
        await self._require_skill(parent_skill_id)
        members = await repo.get_members(_UUID(str(parent_skill_id)))
        return _topological_sort(members)

    async def get_skill_file_content(
        self,
        skill_id: UUID | str,
        path: str,
        *,
        to_run: bool = False,
    ) -> bytes:
        """Get the content of a file in a skill package.

        Args:
            skill_id: The skill ID.
            path: Relative path to the file.
            to_run: Read for a run; see ``get_skill_files``.

        Returns:
            File content as bytes.

        Raises:
            ValueError: If skill is not found or has no S3 storage.
            FileNotFoundError: If the file does not exist.
        """
        skill = await self.get_with_catalog(skill_id, to_run=to_run)

        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        return await self.storage_service.get_file_content(
            await self.packages.resolve_s3_path(skill), path
        )


async def repin_all_catalog_installs(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    storage: SkillStorageService,
    *,
    dry_run: bool = False,
) -> list[tuple[str, SkillRepinResult]]:
    """Repin every pre-package catalog install nobody edited; ``(workspace, result)`` each.

    Each skill is handled in its own session under its own workspace (the
    workspace's install policy applies), so one failure (logged, reported
    ``failed``) leaves the rest to go on and the row as it was.
    """
    from agentarea_common.base.tenant_scope import workspace_scope
    from agentarea_common.constants import PLATFORM_PRINCIPAL_ID

    from agentarea_agents.infrastructure.skill_repository import list_catalog_installs

    async with session_factory() as session:
        rows = await list_catalog_installs(session)
    results: list[tuple[str, SkillRepinResult]] = []
    for skill_id, workspace_id in rows:
        context = UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=workspace_id)
        try:
            with workspace_scope(workspace_id):
                async with session_factory() as session:
                    service = SkillService(
                        RepositoryFactory(session, context), context, storage_service=storage
                    )
                    result = await service.repin_from_catalog(skill_id, dry_run=dry_run)
                    await session.commit()
        except Exception as exc:
            logger.exception("Failed to repin skill %s of workspace %s", skill_id, workspace_id)
            result = SkillRepinResult(str(skill_id), "", "failed", error=str(exc))
        results.append((workspace_id, result))
    return results


def _topological_sort(members: list[SkillMember]) -> list[UUID]:
    """Kahn's algorithm topological sort over SkillMember children.

    Args:
        members: List of SkillMember objects for a parent skill.

    Returns:
        Child skill IDs in valid execution order.

    Raises:
        ValueError: If a circular dependency is detected.
    """
    from uuid import UUID

    skill_ids = {str(m.child_skill_id) for m in members}
    in_degree: dict[str, int] = dict.fromkeys(skill_ids, 0)
    graph: dict[str, list[str]] = {sid: [] for sid in skill_ids}

    for m in members:
        sid = str(m.child_skill_id)
        for dep in m.dependencies or []:
            if dep in skill_ids:
                graph[dep].append(sid)
                in_degree[sid] += 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    result: list[UUID] = []
    visited = 0

    while queue:
        node = queue.pop(0)
        result.append(UUID(node))
        visited += 1
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(skill_ids):
        raise ValueError("Circular dependency detected in skill members")

    return result
