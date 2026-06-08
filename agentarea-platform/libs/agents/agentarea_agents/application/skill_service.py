"""Skill service for managing skills."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from agentarea_common.audit import audited
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.utils.slug import generate_slug

from agentarea_agents.application.skill_parser import SkillParser
from agentarea_agents.domain.skill_models import Skill, SkillMember, SkillSourceType
from agentarea_agents.infrastructure.catalog_skill_repository import (
    CatalogSkillItem,
    CatalogSkillRepository,
)
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubSkillImporter,
)
from agentarea_agents.infrastructure.skill_repository import SkillRepository
from agentarea_agents.infrastructure.skill_storage_service import SkillStorageService
from agentarea_agents.schemas.skills_dto import (
    SkillCreateFromContent,
    SkillEditMetadata,
    SkillImportFromGithub,
)

logger = logging.getLogger(__name__)


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

    Files are NOT materialized: the projection reuses the catalog item's
    ``s3_path`` reference (copy-on-write defers any S3 copy until the user edits
    a file on a forked skill).
    """
    spec = item.spec or {}

    skill = Skill(
        id=UUID(item.id),
        name=item.name,
        slug=generate_slug(item.name),
        description=item.description if item.description is not None else spec.get("description"),
        source_type=spec.get("source_type") or SkillSourceType.CONTENT.value,
        source_url=spec.get("source_url"),
        content=spec.get("content"),
        s3_path=spec.get("s3_path"),
        network_scope=spec.get("network_scope") or "private",
        registry_item_id=item.id,
    )
    # Read-only catalog projection markers consumed by the API DTO.
    skill.is_catalog = True  # type: ignore[attr-defined]
    skill.update_available = False  # type: ignore[attr-defined]
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
    ):
        self.repository_factory = repository_factory
        self.user_context = user_context
        self._storage_service = storage_service
        self._github_importer = github_importer
        self._parser = SkillParser()

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
        repo = self._get_repository()

        # Parse content
        parsed = self._parser.parse_content(payload.content)

        # Use provided values or fall back to parsed values
        skill_name = payload.name or parsed.metadata.name
        skill_description = payload.description or parsed.metadata.description

        # Create skill
        skill = await repo.create(
            name=skill_name,
            slug=await self._resolve_unique_slug(skill_name),
            description=skill_description,
            source_type=SkillSourceType.CONTENT.value,
            content=payload.content,
            source_url=None,
            s3_path=None,
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
            ValueError: If no skill file is found in the ZIP.
        """
        repo = self._get_repository()

        # Parse and extract from ZIP
        parsed, _manifest = self._parser.extract_main_skill_from_zip(zip_data)

        # Use provided values or fall back to parsed values
        skill_name = name or parsed.metadata.name
        skill_description = description or parsed.metadata.description

        # Create skill record first to get ID
        skill = await repo.create(
            name=skill_name,
            slug=await self._resolve_unique_slug(skill_name),
            description=skill_description,
            source_type=SkillSourceType.ZIP.value,
            content=parsed.raw_content,
            source_url=None,
            s3_path=None,  # Will be updated after upload
        )

        # Upload package to S3
        if isinstance(zip_data, bytes):
            import io

            zip_data = io.BytesIO(zip_data)
        zip_data.seek(0)

        s3_path = await self.storage_service.store_package_from_zip(
            skill_id=str(skill.id),
            workspace_id=self.user_context.workspace_id,
            zip_data=zip_data,
        )

        # Update skill with S3 path
        skill = await repo.update(
            str(skill.id),
            s3_path=s3_path,
        )
        if skill is None:
            raise RuntimeError("Failed to update skill package path")

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
        """
        repo = self._get_repository()

        # Download repository as ZIP
        zip_data = await self.github_importer.download_repo(payload.github_url)

        # Parse and extract from ZIP
        import io

        zip_buffer = io.BytesIO(zip_data)
        parsed, _manifest = self._parser.extract_main_skill_from_zip(zip_buffer)

        # Use provided values or fall back to parsed values
        skill_name = payload.name or parsed.metadata.name
        skill_description = payload.description or parsed.metadata.description

        # Create skill record
        skill = await repo.create(
            name=skill_name,
            slug=await self._resolve_unique_slug(skill_name),
            description=skill_description,
            source_type=SkillSourceType.GITHUB.value,
            content=parsed.raw_content,
            source_url=payload.github_url,
            s3_path=None,  # Will be updated after upload
        )

        # Upload to S3
        zip_buffer.seek(0)
        s3_path = await self.storage_service.store_package_from_zip(
            skill_id=str(skill.id),
            workspace_id=self.user_context.workspace_id,
            zip_data=zip_buffer,
        )

        # Update skill with S3 path
        skill = await repo.update(
            str(skill.id),
            s3_path=s3_path,
        )
        if skill is None:
            raise RuntimeError("Failed to update skill package path")

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
        repo = self._get_repository()

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
            skill_name = name or parsed.metadata.name
            skill_description = description or parsed.metadata.description

            # Create skill record
            skill = await repo.create(
                name=skill_name,
                slug=await self._resolve_unique_slug(skill_name),
                description=skill_description,
                source_type=SkillSourceType.PATH.value,
                content=content,
                source_url=None,
                s3_path=None,
            )

            # Upload to S3
            s3_path = await self.storage_service.store_package_from_directory(
                skill_id=str(skill.id),
                workspace_id=self.user_context.workspace_id,
                directory=full_path,
            )

            # Update skill with S3 path
            skill = await repo.update(
                str(skill.id),
                s3_path=s3_path,
            )
            if skill is None:
                raise RuntimeError("Failed to update skill package path")

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
                    forked.update_available = True  # type: ignore[attr-defined]
                continue
            projections.append(_project_catalog_skill(item))
        return projections

    async def list(self) -> list[Skill]:
        """List tenant skills plus catalog skill items projected as read-only.

        A catalog item already forked into the workspace is shadowed by the
        tenant copy; un-forked catalog items appear as read-only projections.

        Returns:
            List of Skill entities.
        """
        repo = self._get_repository()
        tenant_skills = await repo.list_all()
        projections = await self._catalog_projections(tenant_skills)
        return [*tenant_skills, *projections]

    async def list_paginated(
        self,
        limit: int,
        offset: int = 0,
        search: str | None = None,
        source_type: str | None = None,
        has_files: bool | None = None,
        network_scope: str | None = None,
        from_registry: bool | None = None,
    ) -> tuple[list[Skill], int]:
        """List skills with pagination metadata, merging catalog projections.

        Tenant rows and read-only catalog projections are merged into a single
        ordered list (tenant rows first), then paginated in memory. Forked
        catalog items are shadowed by their tenant copy. The optional filters are
        applied to projections too so the merged view stays consistent.
        """
        repo = self._get_repository()
        # Pull the full tenant set so we can dedup catalog items against forks
        # and paginate the merged view consistently.
        tenant_skills = await repo.list_all()
        projections = await self._catalog_projections(tenant_skills)

        merged = [*tenant_skills, *projections]
        merged = self._filter_skills(
            merged,
            search=search,
            source_type=source_type,
            has_files=has_files,
            network_scope=network_scope,
            from_registry=from_registry,
        )
        total = len(merged)
        page = merged[offset : offset + limit]
        return page, total

    @staticmethod
    def _filter_skills(
        skills: list[Skill],
        *,
        search: str | None,
        source_type: str | None,
        has_files: bool | None,
        network_scope: str | None,
        from_registry: bool | None,
    ) -> list[Skill]:
        """Apply list filters to a merged tenant + catalog skill list."""
        result = skills
        if search:
            term = search.strip().lower()
            result = [
                s
                for s in result
                if term in (s.name or "").lower()
                or term in (s.description or "").lower()
                or term in (s.source_url or "").lower()
            ]
        if source_type:
            result = [s for s in result if s.source_type == source_type]
        if has_files is True:
            result = [s for s in result if s.s3_path is not None]
        elif has_files is False:
            result = [s for s in result if s.s3_path is None]
        if network_scope:
            result = [s for s in result if s.network_scope == network_scope]
        if from_registry is True:
            result = [s for s in result if getattr(s, "registry_item_id", None) is not None]
        elif from_registry is False:
            result = [s for s in result if getattr(s, "registry_item_id", None) is None]
        return result

    async def get_with_catalog(self, skill_id: UUID | str) -> Skill | None:
        """Get a tenant skill by id, falling back to a catalog projection.

        Returns the tenant ``skills`` row if present; otherwise projects the
        matching catalog ``registry_item`` (read-only). No DB row is created.
        """
        skill = await self.get(skill_id)
        if skill is not None:
            return skill
        item = await self._get_catalog_repository().get_item(str(skill_id))
        return _project_catalog_skill(item) if item else None

    async def _fork_catalog_skill(self, item: CatalogSkillItem) -> Skill:
        """Copy-on-write: materialize a tenant ``skills`` row from a catalog item.

        Creates a real, owned skill (workspace_id/created_by come from the
        repository's UserContext — never ``platform``), links it back to the
        catalog item via ``registry_item_id``, and records the install on the
        registry item (``installed_entity_id`` + ``installed_version``).

        Copy-on-write semantics: the metadata/spec (name, description,
        source_type, content, s3_path reference) is copied into the tenant row,
        but S3 package files are NOT eagerly copied. The forked skill keeps the
        catalog item's ``s3_path`` reference; the actual S3 file copy is deferred
        until the user first writes a file/content on the fork (see
        :meth:`set_content` / :meth:`replace_package_from_files`).

        Skill members are not copied here: the catalog spec carries metadata
        only, and member edits on a forked bundle go through the member API.
        """
        spec = item.spec or {}
        repo = self._get_repository()
        skill = await repo.create(
            name=item.name,
            slug=await self._resolve_unique_slug(item.name),
            description=item.description
            if item.description is not None
            else spec.get("description"),
            source_type=spec.get("source_type") or SkillSourceType.CONTENT.value,
            content=spec.get("content"),
            source_url=spec.get("source_url"),
            s3_path=spec.get("s3_path"),
            network_scope=spec.get("network_scope") or "private",
            registry_item_id=item.id,
        )
        await self._get_catalog_repository().mark_installed(item.id, str(skill.id), item.version)
        logger.info(
            "Forked catalog skill '%s' (item=%s) into tenant skill %s",
            item.name,
            item.id,
            skill.id,
        )
        return skill

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

    @audited("skill.update", resource_type="skill", resource_id_param="skill_id")
    async def update(
        self,
        skill_id: UUID | str,
        payload: SkillEditMetadata,
    ) -> Skill | None:
        """Update a skill's metadata (name and/or description).

        Uses ``model_dump(exclude_unset=True)`` so omitted fields are left
        unchanged (true PATCH semantics). Never touches files or content; for
        content/file edits use :meth:`set_content` or
        :meth:`replace_package_from_files`.

        Editing a catalog (built-in) skill forks a real tenant copy first
        (copy-on-write) and applies the edit to that copy.

        Args:
            skill_id: The skill ID.
            payload: SkillEditMetadata with optional name / description.

        Returns:
            Updated Skill entity or None if not found.
        """
        repo = self._get_repository()

        skill = await self._resolve_for_edit(skill_id)
        if skill is None:
            return None

        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
        if not update_data:
            return skill

        return await repo.update(str(skill.id), **update_data)

    @audited("skill.update", resource_type="skill", resource_id_param="skill_id")
    async def set_content(
        self,
        skill_id: UUID | str,
        content: str,
    ) -> Skill | None:
        """Replace the SKILL.md content of a content-mode skill.

        Editing a catalog (built-in) skill forks a real tenant copy first
        (copy-on-write) and writes the content to that copy. For a forked skill
        that still references the catalog item's S3 package, the content is
        written to the tenant row directly; lazy S3 file copy on package skills
        is handled by :meth:`replace_package_from_files`.

        Args:
            skill_id: The skill ID.
            content: New SKILL.md text (UTF-8).

        Returns:
            Updated Skill entity or None if not found.
        """
        repo = self._get_repository()
        skill = await self._resolve_for_edit(skill_id)
        if skill is None:
            return None
        return await repo.update(str(skill.id), content=content)

    @audited("skill.update", resource_type="skill", resource_id_param="skill_id")
    async def replace_package_from_files(
        self,
        skill_id: UUID | str,
        files: dict[str, str],
    ) -> Skill:
        """Replace a package-mode skill's file tree with the given map.

        Overwrites by S3 key, then deletes any orphaned keys (present in old
        package but absent in the new map). Same crash window as
        ``create_from_zip``: a failure mid-write leaves a partial package.

        Requires the skill to be package-mode (``s3_path`` set). Multi-file
        edits on content-mode skills must go through delete + recreate.

        Editing a catalog (built-in) skill forks a real tenant copy first
        (copy-on-write). Copy-on-write S3 handling: a forked skill's ``s3_path``
        still references the catalog item's (foreign) prefix. Writing files
        always targets the tenant's OWN prefix (``skills/{workspace}/{skill}/``);
        when that differs from the current ``s3_path`` (i.e. the skill still
        points at the shared catalog package), the new tenant prefix is adopted
        and the foreign catalog files are NEVER deleted — the write is the
        copy-then-write. Orphan deletion only happens when re-writing the skill's
        own already-owned prefix.

        Args:
            skill_id: The skill ID.
            files: Map of relative path -> file text content. Must include a
                root-level ``SKILL.md`` (case-insensitive).

        Returns:
            Updated Skill entity.

        Raises:
            ValueError: skill not found, skill is content-mode, or files
                missing SKILL.md.
        """
        import io
        import zipfile

        repo = self._get_repository()
        skill = await self._resolve_for_edit(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        if not skill.s3_path:
            raise ValueError(
                f"Skill {skill_id} is content-mode; multi-file edits not supported. "
                "Delete and recreate as a package."
            )

        skill_md_keys = [k for k in files if k.lower() in ("skill.md", "skill.markdown")]
        if not skill_md_keys:
            raise ValueError("files must include a SKILL.md at the root")
        new_skill_md_text = files[skill_md_keys[0]]

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, text in files.items():
                zf.writestr(path, text)

        # The tenant's OWN package prefix. If the skill still references a
        # foreign (catalog) prefix, this differs and we copy-on-write into the
        # tenant prefix instead of mutating the shared catalog package.
        owns_package = skill.s3_path == self.storage_service._get_s3_prefix(
            self.user_context.workspace_id, str(skill.id)
        )

        old_keys = (
            {f.path for f in await self.storage_service.list_files(skill.s3_path)}
            if owns_package
            else set()
        )
        new_keys = set(files.keys())

        new_s3_path = await self.storage_service.store_package_from_zip(
            skill_id=str(skill.id),
            workspace_id=self.user_context.workspace_id,
            zip_data=buffer.getvalue(),
        )

        orphans = old_keys - new_keys
        if owns_package and orphans:
            prefix = skill.s3_path.rstrip("/") + "/"
            self.storage_service.client.delete_objects(
                Bucket=self.storage_service.bucket_name,
                Delete={"Objects": [{"Key": f"{prefix}{p}"} for p in orphans]},
            )

        skill = await repo.update(str(skill.id), content=new_skill_md_text, s3_path=new_s3_path)
        if skill is None:
            raise RuntimeError("Failed to update skill content")
        logger.info(
            f"Replaced package for skill {skill.id}: {len(files)} files written, "
            f"{len(orphans)} orphans removed (copy_on_write={not owns_package})"
        )
        return skill

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

        # Delete from S3 if applicable
        if skill.s3_path:
            try:
                await self.storage_service.delete_package(skill.s3_path)
            except Exception as e:
                logger.warning(f"Failed to delete S3 package for skill {skill_id}: {e}")

        # Delete from database
        await repo.delete(str(skill_id))

        logger.info(f"Deleted skill {skill_id}")
        return True

    async def get_skill_files(
        self,
        skill_id: UUID | str,
        include_urls: bool = False,
    ) -> list[SkillFileInfo]:
        """Get list of files in a skill package.

        Args:
            skill_id: The skill ID.
            include_urls: If True, include presigned URLs for each file.

        Returns:
            List of SkillFileInfo objects.

        Raises:
            ValueError: If skill is not a multi-file package.
        """
        repo = self._get_repository()
        skill = await repo.get_by_id(skill_id)

        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        if not skill.s3_path:
            # Content-only skill
            return [SkillFileInfo(path="SKILL.md", size=len(skill.content or ""))]

        files = await self.storage_service.list_files(skill.s3_path)

        result = []
        for file_info in files:
            skill_file = SkillFileInfo(
                path=file_info.path,
                size=file_info.size,
            )

            if include_urls:
                skill_file.url = await self.storage_service.get_file_url(
                    skill.s3_path,
                    file_info.path,
                )

            result.append(skill_file)

        return result

    async def get_skill_file_url(
        self,
        skill_id: UUID | str,
        path: str,
        expires_in: int = 3600,
    ) -> str:
        """Get a presigned URL for a file in a skill package.

        Args:
            skill_id: The skill ID.
            path: Relative path to the file.
            expires_in: URL expiration time in seconds.

        Returns:
            Presigned URL.

        Raises:
            ValueError: If skill is not found or has no S3 storage.
        """
        repo = self._get_repository()
        skill = await repo.get_by_id(skill_id)

        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        if not skill.s3_path:
            raise ValueError(f"Skill {skill_id} has no file storage (content-only)")

        return await self.storage_service.get_file_url(
            skill.s3_path,
            path,
            expires_in=expires_in,
        )

    # ------------------------------------------------------------------
    # Skill member management (skill-as-bundle / self-referential)
    # ------------------------------------------------------------------

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
            ValueError: If the parent or child skill is not found, or if adding
                        the child would create a cycle.
        """
        from uuid import UUID as _UUID

        parent_id = _UUID(str(parent_skill_id))
        child_id = _UUID(str(child_skill_id))

        repo = self._get_repository()

        if parent_id == child_id:
            raise ValueError("A skill cannot be a member of itself")

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
        return await repo.get_members(_UUID(str(parent_skill_id)))

    async def flatten(self, parent_skill_id: UUID | str) -> list[UUID]:
        """Return child skill IDs in topological execution order.

        Raises:
            ValueError: If circular dependencies are detected.
        """
        from uuid import UUID as _UUID

        repo = self._get_repository()
        members = await repo.get_members(_UUID(str(parent_skill_id)))
        return _topological_sort(members)

    async def get_skill_file_content(
        self,
        skill_id: UUID | str,
        path: str,
    ) -> bytes:
        """Get the content of a file in a skill package.

        Args:
            skill_id: The skill ID.
            path: Relative path to the file.

        Returns:
            File content as bytes.

        Raises:
            ValueError: If skill is not found or has no S3 storage.
            FileNotFoundError: If the file does not exist.
        """
        repo = self._get_repository()
        skill = await repo.get_by_id(skill_id)

        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        if not skill.s3_path:
            # For content-only skills, return the content if requesting the main file
            if path in ("SKILL.md", "skill.md"):
                return (skill.content or "").encode("utf-8")
            raise FileNotFoundError(f"File not found: {path}")

        return await self.storage_service.get_file_content(skill.s3_path, path)


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
