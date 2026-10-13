"""Skill parser for parsing markdown files with YAML frontmatter."""

import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, ClassVar

import frontmatter
import yaml
from frontmatter.default_handlers import YAMLHandler

from .skill_package_limits import check_zip_budget

_ENTRY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_.-]*):(?:[ \t]+(?P<value>.*))?$")
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?[0-9]?[+-]?\s*(#.*)?$")
_STRUCTURED_VALUE_START = ("'", '"', "[", "{")


class SkillFrontmatterError(ValueError):
    """A SKILL.md frontmatter block that cannot be read; the message names the line."""


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split SKILL.md into its frontmatter mapping and markdown body.

    Strict YAML first, so every valid file reads exactly as YAML says. When
    strict YAML refuses the block, it is read the way agentskills and Claude
    Code read it, one top-level entry at a time:

    - a top-level entry is a ``key: value`` line plus the lines that continue
      it (indented lines, ``- item`` lines, blank lines between them);
    - an entry is first parsed as YAML on its own, so quoted values, flow
      lists, block scalars and nested maps/lists keep their YAML meaning;
    - only a plain (unquoted, non-flow) scalar that YAML refuses is taken
      literally: the value is everything after the first ``": "``, with
      indented continuation lines folded in with a space;
    - blank lines and ``#`` comments between entries are skipped.

    Anything else is a genuinely broken block and raises ``SkillFrontmatterError`` naming
    the file line: a line that is not ``key: value``, a quoted or flow value
    YAML cannot parse, or a nested block (``metadata:``, ``allowed-tools:``)
    that is not valid YAML itself.
    """
    try:
        post = frontmatter.loads(content)
    except yaml.YAMLError:
        text = content.strip()
        block, body = YAMLHandler().split(text)
        leading_lines = content[: len(content) - len(content.lstrip())].count("\n")
        first_line = leading_lines + text[: text.find(block)].count("\n") + 1
        return _parse_frontmatter_entries(block, first_line), body.strip()
    return dict(post.metadata), post.content


def _parse_frontmatter_entries(block: str, first_line: int) -> dict[str, Any]:
    lines = block.split("\n")
    metadata: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        match = _ENTRY_RE.match(line.rstrip())
        if match is None:
            raise SkillFrontmatterError(
                f"SKILL.md frontmatter line {first_line + index} is not a 'key: value' "
                f"entry: {line.strip()!r}"
            )
        end = index + 1
        while end < len(lines) and (
            not lines[end].strip() or lines[end][0] in " \t" or lines[end].startswith("-")
        ):
            end += 1
        while end > index + 1 and not lines[end - 1].strip():
            end -= 1
        key = match.group("key")
        metadata[key] = _parse_entry(
            key, match.group("value") or "", lines[index:end], first_line + index
        )
        index = end
    return metadata


def _parse_entry(key: str, value: str, entry_lines: list[str], line_number: int) -> Any:
    try:
        parsed = yaml.safe_load("\n".join(entry_lines))
    except yaml.YAMLError as exc:
        continuation = entry_lines[1:]
        is_plain_scalar = (
            bool(value)
            and not value.startswith(_STRUCTURED_VALUE_START)
            and not _BLOCK_SCALAR_RE.match(value)
            and all(not line.strip() or line[0] in " \t" for line in continuation)
        )
        if is_plain_scalar:
            parts = [value.strip(), *(line.strip() for line in continuation if line.strip())]
            return " ".join(parts)
        mark = getattr(exc, "problem_mark", None)
        offset = min(mark.line, len(entry_lines) - 1) if mark is not None else 0
        problem = getattr(exc, "problem", None) or str(exc).split("\n")[0]
        raise SkillFrontmatterError(
            f"SKILL.md frontmatter line {line_number + offset} ('{key}') is not valid YAML: "
            f"{problem}: {entry_lines[offset].strip()!r}"
        ) from exc
    (entry_value,) = parsed.values()
    return entry_value


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
    NOT_A_ZIP_MESSAGE: ClassVar[str] = "Skill package is not a valid ZIP archive"

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
            raw_frontmatter, body = parse_frontmatter(content)

            # Extract metadata
            name_value = raw_frontmatter.get("name", "")
            name = name_value if isinstance(name_value, str) else ""
            if not name:
                # Try to extract name from first heading
                lines = body.strip().split("\n")
                for line in lines:
                    if line.startswith("# "):
                        name = line[2:].strip()
                        break

            if not name:
                name = "Unnamed Skill"

            description_value = raw_frontmatter.get("description")
            allowed_tools_value = raw_frontmatter.get("allowed-tools", [])
            allowed_tools = (
                [str(tool) for tool in allowed_tools_value]
                if isinstance(allowed_tools_value, list)
                else []
            )

            metadata = SkillMetadata(
                name=name,
                description=description_value if isinstance(description_value, str) else None,
                allowed_tools=allowed_tools,
                raw_frontmatter=raw_frontmatter,
            )

            return ParsedSkill(
                metadata=metadata,
                content=body,
                raw_content=content,
            )

        except SkillFrontmatterError:
            raise
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

        Raises:
            ValueError: If the data is not a ZIP archive or is over budget.
        """
        if isinstance(zip_data, bytes):
            zip_data = io.BytesIO(zip_data)

        try:
            zf = zipfile.ZipFile(zip_data, "r")
        except zipfile.BadZipFile as e:
            raise ValueError(self.NOT_A_ZIP_MESSAGE) from e
        with zf:
            check_zip_budget(zf)
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
            ValueError: If the data is not a ZIP archive or no skill file is
                found in it.
        """
        if isinstance(zip_data, bytes):
            zip_data = io.BytesIO(zip_data)

        try:
            return self._extract_main_skill_from_zip(zip_data)
        except zipfile.BadZipFile as e:
            raise ValueError(self.NOT_A_ZIP_MESSAGE) from e

    def _extract_main_skill_from_zip(
        self, zip_data: BinaryIO
    ) -> tuple[ParsedSkill, SkillPackageManifest]:
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
