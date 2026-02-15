"""Skill service for managing skills."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory

from agentarea_agents.application.skill_parser import ParsedSkill, SkillParser
from agentarea_agents.domain.skill_models import Skill, SkillSourceType
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubSkillImporter,
    GitHubSkillImporterError,
)
from agentarea_agents.infrastructure.skill_repository import SkillRepository
from agentarea_agents.infrastructure.skill_storage_service import (
    FileInfo,
    SkillStorageService,
)

logger = logging.getLogger(__name__)


@dataclass
class SkillFileInfo:
    """Information about a file in a skill package."""

    path: str
    size: int
    url: str | None = None  # Presigned URL if requested


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

    async def create_from_content(
        self,
        content: str,
        name: str | None = None,
        description: str | None = None,
    ) -> Skill:
        """Create a skill from raw markdown content.

        Args:
            content: Raw markdown content with optional YAML frontmatter.
            name: Optional name override (extracted from frontmatter if not provided).
            description: Optional description override.

        Returns:
            Created Skill entity.
        """
        repo = self._get_repository()

        # Parse content
        parsed = self._parser.parse_content(content)

        # Use provided values or fall back to parsed values
        skill_name = name or parsed.metadata.name
        skill_description = description or parsed.metadata.description

        # Create skill
        skill = await repo.create(
            name=skill_name,
            description=skill_description,
            source_type=SkillSourceType.CONTENT.value,
            content=content,
            source_url=None,
            s3_path=None,
        )

        logger.info(f"Created skill '{skill_name}' from content (id={skill.id})")
        return skill

    async def create_from_zip(
        self,
        zip_data: bytes | BinaryIO,
        name: str | None = None,
        description: str | None = None,
    ) -> Skill:
        """Create a skill from an uploaded ZIP file.

        Args:
            zip_data: ZIP file as bytes or file-like object.
            name: Optional name override.
            description: Optional description override.

        Returns:
            Created Skill entity.

        Raises:
            ValueError: If no skill file is found in the ZIP.
        """
        repo = self._get_repository()

        # Parse and extract from ZIP
        parsed, manifest = self._parser.extract_main_skill_from_zip(zip_data)

        # Use provided values or fall back to parsed values
        skill_name = name or parsed.metadata.name
        skill_description = description or parsed.metadata.description

        # Create skill record first to get ID
        skill = await repo.create(
            name=skill_name,
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

        logger.info(f"Created skill '{skill_name}' from ZIP (id={skill.id})")
        return skill

    async def create_from_github(
        self,
        github_url: str,
        name: str | None = None,
        description: str | None = None,
    ) -> Skill:
        """Create a skill from a GitHub repository.

        Args:
            github_url: GitHub repository URL.
            name: Optional name override.
            description: Optional description override.

        Returns:
            Created Skill entity.

        Raises:
            GitHubSkillImporterError: If download fails.
            ValueError: If no skill file is found in the repository.
        """
        repo = self._get_repository()

        # Download repository as ZIP
        zip_data = await self.github_importer.download_repo(github_url)

        # Parse and extract from ZIP
        import io
        zip_buffer = io.BytesIO(zip_data)
        parsed, manifest = self._parser.extract_main_skill_from_zip(zip_buffer)

        # Use provided values or fall back to parsed values
        skill_name = name or parsed.metadata.name
        skill_description = description or parsed.metadata.description

        # Create skill record
        skill = await repo.create(
            name=skill_name,
            description=skill_description,
            source_type=SkillSourceType.GITHUB.value,
            content=parsed.raw_content,
            source_url=github_url,
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

        logger.info(f"Created skill '{skill_name}' from GitHub: {github_url} (id={skill.id})")
        return skill

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
                raise ValueError(f"No skill file found in directory: {full_path}")

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

    async def list(self) -> list[Skill]:
        """List all skills in the workspace.

        Returns:
            List of Skill entities.
        """
        repo = self._get_repository()
        return await repo.list_all()

    async def update(
        self,
        skill_id: UUID | str,
        name: str | None = None,
        description: str | None = None,
        content: str | None = None,
    ) -> Skill | None:
        """Update a skill.

        Args:
            skill_id: The skill ID.
            name: Optional new name.
            description: Optional new description.
            content: Optional new content (only for content-type skills).

        Returns:
            Updated Skill entity or None if not found.
        """
        repo = self._get_repository()

        # Build update dict
        update_data = {}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if content is not None:
            update_data["content"] = content

        if not update_data:
            return await repo.get_by_id(skill_id)

        return await repo.update(str(skill_id), **update_data)

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
