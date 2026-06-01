"""Skill parser for parsing markdown files with YAML frontmatter."""

import io
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, ClassVar

import frontmatter


@dataclass
class SkillMetadata:
    """Parsed metadata from skill frontmatter."""

    name: str
    description: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    raw_frontmatter: dict = field(default_factory=dict)


@dataclass
class ParsedSkill:
    """Result of parsing a skill file."""

    metadata: SkillMetadata
    content: str  # The markdown body (without frontmatter)
    raw_content: str  # The full raw content (with frontmatter)


@dataclass
class SkillFileInfo:
    """Information about a file in a skill package."""

    path: str  # Relative path within the package
    size: int
    is_main_skill: bool = False


@dataclass
class SkillPackageManifest:
    """Manifest of files in a skill package."""

    main_skill_path: str | None
    files: list[SkillFileInfo]
    total_size: int


class SkillParser:
    """Parser for skill files and packages.

    Skills follow the Claude Code Skills format:
    - YAML frontmatter with metadata (name, description, allowed-tools)
    - Markdown body with instructions
    """

    # Valid main skill file patterns
    MAIN_SKILL_PATTERNS: ClassVar[list[str]] = [
        "SKILL.md",
        "skill.md",
    ]
    MISSING_SKILL_MESSAGE: ClassVar[str] = (
        "No SKILL.md found at package root. Skills must include a SKILL.md file."
    )

    def parse_content(self, content: str) -> ParsedSkill:
        """Parse raw markdown content with frontmatter.

        Args:
            content: Raw markdown content with optional YAML frontmatter.

        Returns:
            ParsedSkill with metadata and body content.

        Raises:
            ValueError: If the content cannot be parsed.
        """
        try:
            post = frontmatter.loads(content)

            # Extract metadata
            name_value = post.get("name", "")
            name = name_value if isinstance(name_value, str) else ""
            if not name:
                # Try to extract name from first heading
                lines = post.content.strip().split("\n")
                for line in lines:
                    if line.startswith("# "):
                        name = line[2:].strip()
                        break

            if not name:
                name = "Unnamed Skill"

            description_value = post.get("description")
            allowed_tools_value = post.get("allowed-tools", [])
            allowed_tools = [
                str(tool) for tool in allowed_tools_value
            ] if isinstance(allowed_tools_value, list) else []

            metadata = SkillMetadata(
                name=name,
                description=description_value if isinstance(description_value, str) else None,
                allowed_tools=allowed_tools,
                raw_frontmatter=dict(post.metadata),
            )

            return ParsedSkill(
                metadata=metadata,
                content=post.content,
                raw_content=content,
            )

        except Exception as e:
            raise ValueError(f"Failed to parse skill content: {e}") from e

    def find_main_skill_file(self, file_paths: list[str]) -> str | None:
        """Find the main skill file in a list of file paths.

        Looks for:
        1. SKILL.md or skill.md in root

        Args:
            file_paths: List of relative file paths in the package.

        Returns:
            Path to the main skill file, or None if not found.
        """
        # Normalize paths and filter to root-level files
        root_files = []
        for path in file_paths:
            # Normalize path separators
            normalized = path.replace("\\", "/")
            # Check if it's a root-level file (no directory separators after stripping leading)
            parts = normalized.strip("/").split("/")
            if len(parts) == 1:
                root_files.append(normalized)

        # Priority 1: Exact match for SKILL.md patterns
        for pattern in self.MAIN_SKILL_PATTERNS:
            for file_path in root_files:
                if file_path.lower() == pattern.lower():
                    return file_path

        return None

    def build_manifest_from_paths(
        self, file_paths: list[str], file_sizes: dict[str, int] | None = None
    ) -> SkillPackageManifest:
        """Build a manifest from a list of file paths.

        Args:
            file_paths: List of relative file paths.
            file_sizes: Optional dict mapping paths to sizes.

        Returns:
            SkillPackageManifest with file information.
        """
        file_sizes = file_sizes or {}
        main_skill_path = self.find_main_skill_file(file_paths)

        files = []
        total_size = 0

        for path in file_paths:
            size = file_sizes.get(path, 0)
            total_size += size
            files.append(
                SkillFileInfo(
                    path=path,
                    size=size,
                    is_main_skill=(path == main_skill_path),
                )
            )

        return SkillPackageManifest(
            main_skill_path=main_skill_path,
            files=files,
            total_size=total_size,
        )

    def build_manifest_from_zip(self, zip_data: bytes | BinaryIO) -> SkillPackageManifest:
        """Build a manifest from a ZIP file.

        Args:
            zip_data: ZIP file as bytes or file-like object.

        Returns:
            SkillPackageManifest with file information.
        """
        if isinstance(zip_data, bytes):
            zip_data = io.BytesIO(zip_data)

        with zipfile.ZipFile(zip_data, "r") as zf:
            file_paths = []
            file_sizes = {}

            for info in zf.infolist():
                # Skip directories
                if info.is_dir():
                    continue

                # Skip hidden files and __MACOSX
                if info.filename.startswith("__MACOSX") or "/." in info.filename:
                    continue

                # Handle potential root folder in zip (e.g., repo-main/)
                path = self._normalize_zip_path(info.filename, zf.namelist())
                if path:
                    file_paths.append(path)
                    file_sizes[path] = info.file_size

            return self.build_manifest_from_paths(file_paths, file_sizes)

    def build_manifest_from_directory(self, directory: str | Path) -> SkillPackageManifest:
        """Build a manifest from a local directory.

        Args:
            directory: Path to the directory.

        Returns:
            SkillPackageManifest with file information.
        """
        directory = Path(directory)
        file_paths = []
        file_sizes = {}

        for root, _, files in os.walk(directory):
            for filename in files:
                # Skip hidden files
                if filename.startswith("."):
                    continue

                full_path = Path(root) / filename
                relative_path = str(full_path.relative_to(directory))
                # Normalize to forward slashes
                relative_path = relative_path.replace("\\", "/")

                file_paths.append(relative_path)
                file_sizes[relative_path] = full_path.stat().st_size

        return self.build_manifest_from_paths(file_paths, file_sizes)

    def extract_main_skill_from_zip(
        self, zip_data: bytes | BinaryIO
    ) -> tuple[ParsedSkill, SkillPackageManifest]:
        """Extract and parse the main skill from a ZIP file.

        Args:
            zip_data: ZIP file as bytes or file-like object.

        Returns:
            Tuple of (parsed skill, manifest).

        Raises:
            ValueError: If no skill file is found in the ZIP.
        """
        if isinstance(zip_data, bytes):
            zip_data = io.BytesIO(zip_data)

        manifest = self.build_manifest_from_zip(zip_data)

        if not manifest.main_skill_path:
            raise ValueError(self.MISSING_SKILL_MESSAGE)

        # Reset file pointer and extract content
        zip_data.seek(0)

        with zipfile.ZipFile(zip_data, "r") as zf:
            # Find the actual path in the zip (may have root folder prefix)
            actual_path = self._find_actual_zip_path(manifest.main_skill_path, zf.namelist())
            if not actual_path:
                raise ValueError(f"Could not find {manifest.main_skill_path} in ZIP")

            content = zf.read(actual_path).decode("utf-8")
            parsed = self.parse_content(content)

        return parsed, manifest

    def _normalize_zip_path(self, path: str, all_paths: list[str]) -> str | None:
        """Normalize a zip file path, removing common root folder if present.

        Many ZIP files (especially from GitHub) have a root folder like 'repo-main/'.
        This method strips that common prefix.

        Args:
            path: The file path from the ZIP.
            all_paths: All paths in the ZIP for detecting common prefix.

        Returns:
            Normalized path, or None if the file should be skipped.
        """
        # Skip directories
        if path.endswith("/"):
            return None

        # Find common root folder
        non_dir_paths = [
            p for p in all_paths if not p.endswith("/") and not p.startswith("__MACOSX")
        ]
        if not non_dir_paths:
            return path

        # Check if all paths share a common root folder
        first_parts = set()
        for p in non_dir_paths:
            parts = p.split("/")
            if len(parts) > 1:
                first_parts.add(parts[0])

        # If all files are under one root folder, strip it
        if len(first_parts) == 1:
            root_folder = first_parts.pop() + "/"
            if path.startswith(root_folder):
                return path[len(root_folder) :]

        return path

    def _find_actual_zip_path(self, normalized_path: str, all_paths: list[str]) -> str | None:
        """Find the actual path in the ZIP for a normalized path.

        Args:
            normalized_path: The normalized (root-stripped) path.
            all_paths: All paths in the ZIP.

        Returns:
            The actual path in the ZIP, or None if not found.
        """
        # Direct match
        if normalized_path in all_paths:
            return normalized_path

        # Check with common root prefix
        non_dir_paths = [
            p for p in all_paths if not p.endswith("/") and not p.startswith("__MACOSX")
        ]
        if not non_dir_paths:
            return None

        first_parts = set()
        for p in non_dir_paths:
            parts = p.split("/")
            if len(parts) > 1:
                first_parts.add(parts[0])

        if len(first_parts) == 1:
            root_folder = first_parts.pop()
            prefixed_path = f"{root_folder}/{normalized_path}"
            if prefixed_path in all_paths:
                return prefixed_path

        return None
