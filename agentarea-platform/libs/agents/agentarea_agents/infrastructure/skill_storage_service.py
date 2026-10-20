"""Skill storage service for S3 operations."""

import io
import logging
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO

from agentarea_common.config.aws import get_aws_settings, get_s3_client
from botocore.exceptions import ClientError

from ..application.skill_package_limits import (
    MAX_PACKAGE_FILE_BYTES,
    MAX_PACKAGE_FILES,
    MAX_PACKAGE_TOTAL_BYTES,
    check_zip_budget,
    read_entry,
    safe_package_path,
)

logger = logging.getLogger(__name__)

SKILLS_PREFIX = "skills"
# Immutable packages of the platform registries' skills, keyed by the digest
# of their files. Shared by every workspace: what is stored here is public
# catalog content, and no tenant edit ever writes under it (an edit copies into
# the tenant's own prefix first). A workspace registry's packages live in that
# workspace's own area (``catalog_area``).
CATALOG_PREFIX = f"{SKILLS_PREFIX}/catalog"
CATALOG_AREA = "catalog"
# A workspace's own skill bodies (authored, uploaded, imported or edited), each
# an immutable package keyed by its digest. An edit stores a new package and
# moves the skill's pointer; the old one stays, which is the skill's history.
PACKAGES_AREA = "packages"


def catalog_area(workspace_id: str | None) -> str:
    """Where catalog packages live: one shared area for the platform's registries,
    and each workspace's own area for its registries, so private content never
    lands where another tenant reads.
    """
    return (
        CATALOG_PREFIX if workspace_id is None else f"{SKILLS_PREFIX}/{workspace_id}/{CATALOG_AREA}"
    )


def tenant_package_prefix(workspace_id: str, skill_id: str) -> str:
    """The mutable prefix a workspace's own copy of a skill lived under before packages.

    Nothing writes here any more; a skill still pointing here is moved into a
    package the first time it is read.
    """
    return f"{SKILLS_PREFIX}/{workspace_id}/{skill_id}/"


def workspace_package_area(workspace_id: str) -> str:
    """Where a workspace's own immutable packages live, inside its own prefix."""
    return f"{SKILLS_PREFIX}/{workspace_id}/{PACKAGES_AREA}"


def is_catalog_package(s3_path: str | None) -> bool:
    """An immutable package stored by digest, in the shared or a workspace's area."""
    parts = str(s3_path or "").split("/")
    return len(parts) > 2 and parts[0] == SKILLS_PREFIX and CATALOG_AREA in (parts[1], parts[2])


def is_workspace_package(s3_path: str | None) -> bool:
    """A workspace's own immutable package (``skills/<ws>/packages/<digest>/``)."""
    parts = str(s3_path or "").split("/")
    return len(parts) > 3 and parts[0] == SKILLS_PREFIX and parts[2] == PACKAGES_AREA


def is_immutable_package(s3_path: str | None) -> bool:
    """A package keyed by its digest: its files never change."""
    return is_catalog_package(s3_path) or is_workspace_package(s3_path)


def package_digest_of(s3_path: str | None) -> str | None:
    """The digest an immutable package is keyed by, read off its path."""
    if not is_immutable_package(s3_path):
        return None
    return str(s3_path).rstrip("/").rsplit("/", 1)[-1]


def package_digest(files: Mapping[str, bytes]) -> str:
    """sha256 over the sorted (path, bytes) pairs, each length-prefixed."""
    digest = sha256()
    for path in sorted(files):
        for part in (path.encode("utf-8"), files[path]):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def checked_package_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    """The file set with every path normalised, or ``ValueError`` for the whole set."""
    if len(files) > MAX_PACKAGE_FILES:
        raise ValueError(f"Skill package contains more than {MAX_PACKAGE_FILES} files")
    checked: dict[str, bytes] = {}
    total = 0
    for path, data in files.items():
        if len(data) > MAX_PACKAGE_FILE_BYTES:
            mb = MAX_PACKAGE_FILE_BYTES // (1024 * 1024)
            raise ValueError(f"Skill package file {path!r} is larger than {mb} MB")
        total += len(data)
        checked[safe_package_path(path)] = data
    if total > MAX_PACKAGE_TOTAL_BYTES:
        mb = MAX_PACKAGE_TOTAL_BYTES // (1024 * 1024)
        raise ValueError(f"Skill package is larger than {mb} MB uncompressed")
    return checked


def _github_tree_alias(tree_sha: str, workspace_id: str | None) -> str:
    return f"{catalog_area(workspace_id)}/github-tree/{tree_sha}"


@dataclass
class FileInfo:
    """Information about a stored file."""

    path: str
    size: int
    content_type: str | None = None


class SkillStorageService:
    """Service for storing skill packages in S3.

    Every package is immutable and keyed by the sha256 of its files: a
    workspace's own at s3://{bucket}/skills/{workspace_id}/packages/{sha256}/, a
    catalog skill's at s3://{bucket}/skills/catalog/{sha256}/ (or its
    workspace registry's area). Skills stored before that live at
    skills/{workspace_id}/{skill_id}/ until they are next read.
    """

    SKILLS_PREFIX = SKILLS_PREFIX

    def __init__(self):
        self._client = None
        self._settings = None

    @property
    def client(self):
        """Lazy-load S3 client."""
        if self._client is None:
            self._client = get_s3_client()
        return self._client

    @property
    def settings(self):
        """Lazy-load AWS settings."""
        if self._settings is None:
            self._settings = get_aws_settings()
        return self._settings

    @property
    def bucket_name(self) -> str:
        """S3 bucket name. Skills share the artifacts bucket and live under
        the ``skills/`` prefix — keeps storage to one bucket per workspace.
        """
        return self.settings.ARTIFACTS_BUCKET

    def _get_s3_prefix(self, workspace_id: str, skill_id: str) -> str:
        """Get the S3 prefix for a skill package.

        Args:
            workspace_id: The workspace ID.
            skill_id: The skill ID.

        Returns:
            S3 key prefix: skills/{workspace_id}/{skill_id}/
        """
        return tenant_package_prefix(workspace_id, skill_id)

    async def store_catalog_package(
        self, files: Mapping[str, bytes], *, workspace_id: str | None = None
    ) -> str:
        """Store a catalog package under its digest, once; return its prefix.

        ``workspace_id`` is the owner of a workspace registry's item; a
        platform registry's item goes to the shared area.
        """
        return await self._store_by_digest(catalog_area(workspace_id), files)

    async def store_workspace_package(self, files: Mapping[str, bytes], workspace_id: str) -> str:
        """Store a workspace's own skill body under its digest, once; return its prefix."""
        return await self._store_by_digest(workspace_package_area(workspace_id), files)

    async def _store_by_digest(self, area: str, files: Mapping[str, bytes]) -> str:
        """Store ``files`` at ``<area>/<digest>/``.

        A prefix already holding every path is reused as is: the key is the
        digest, so the same paths there are the same bytes. One holding only
        some of them (an earlier store that died midway) is completed.
        """
        checked = checked_package_files(files)
        prefix = f"{area}/{package_digest(checked)}/"
        stored = {f.path for f in await self.list_files(prefix)}
        missing = [path for path in checked if path not in stored]
        for path in missing:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"{prefix}{path}",
                Body=checked[path],
                ContentType=self._guess_content_type(path),
            )
        if missing:
            logger.info("Stored skill package %s (%d files)", prefix, len(missing))
        return prefix

    async def read_package(self, s3_path: str) -> dict[str, bytes]:
        """Every file of a package, by relative path."""
        return {
            info.path: await self.get_file_content(s3_path, info.path)
            for info in await self.list_files(s3_path)
        }

    async def get_github_tree_package(
        self, tree_sha: str, *, workspace_id: str | None = None
    ) -> str | None:
        """The catalog package a GitHub tree was stored as in an area, if it was."""
        try:
            response = self.client.get_object(
                Bucket=self.bucket_name, Key=_github_tree_alias(tree_sha, workspace_id)
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise
        return response["Body"].read().decode("utf-8")

    async def put_github_tree_package(
        self, tree_sha: str, s3_path: str, *, workspace_id: str | None = None
    ) -> None:
        """Record which catalog package a GitHub tree is, so it is fetched once."""
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=_github_tree_alias(tree_sha, workspace_id),
            Body=s3_path.encode("utf-8"),
            ContentType="text/plain",
        )

    def _package_entries(self, zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
        """Return the archive's stored entries with their package paths.

        Checks the declared size budget and every path before any entry is
        read, so a bad archive is refused whole rather than half-uploaded.

        Raises:
            ValueError: If the archive is over budget or holds a path that is
                not a plain relative package path.
        """
        check_zip_budget(zf)
        # Detect common root folder (GitHub style)
        root_folder = self._detect_root_folder(zf.namelist())

        entries: list[tuple[zipfile.ZipInfo, str]] = []
        for info in zf.infolist():
            # Skip directories
            if info.is_dir():
                continue

            # Skip hidden and system files
            if self._should_skip_file(info.filename):
                continue

            # Strip root folder if present
            relative_path = info.filename
            if root_folder and relative_path.startswith(root_folder):
                relative_path = relative_path[len(root_folder) :]

            if not relative_path:
                continue

            entries.append((info, safe_package_path(relative_path)))
        return entries

    def files_from_zip(self, zip_data: bytes | BinaryIO) -> dict[str, bytes]:
        """The package a ZIP upload holds, by path; every path and the budget checked first.

        Raises:
            ValueError: If the data is not a ZIP archive, is over budget, or
                holds a path that is not a plain relative package path.
        """
        if isinstance(zip_data, bytes):
            zip_data = io.BytesIO(zip_data)
        zip_data.seek(0)
        try:
            zf = zipfile.ZipFile(zip_data, "r")
        except zipfile.BadZipFile as e:
            raise ValueError("Skill package is not a valid ZIP archive") from e
        with zf:
            return {path: read_entry(zf, info) for info, path in self._package_entries(zf)}

    @staticmethod
    def files_from_directory(directory: str | Path) -> dict[str, bytes]:
        """The package a local directory holds, by path; hidden files left out."""
        directory = Path(directory)
        return {
            str(file_path.relative_to(directory)).replace("\\", "/"): file_path.read_bytes()
            for file_path in sorted(directory.rglob("*"))
            if file_path.is_file()
            and not any(part.startswith(".") for part in file_path.relative_to(directory).parts)
        }

    async def get_file_url(
        self,
        s3_path: str,
        relative_path: str,
        expires_in: int = 3600,
    ) -> str:
        """Get a presigned URL for a file in a skill package.

        Args:
            s3_path: S3 prefix for the skill package.
            relative_path: Relative path to the file within the package.
            expires_in: URL expiration time in seconds (default 1 hour).

        Returns:
            Presigned URL for the file.
        """
        s3_key = f"{s3_path.rstrip('/')}/{safe_package_path(relative_path)}"

        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": s3_key,
            },
            ExpiresIn=expires_in,
        )

        return url

    async def get_file_content(
        self,
        s3_path: str,
        relative_path: str,
    ) -> bytes:
        """Get the content of a file in a skill package.

        Args:
            s3_path: S3 prefix for the skill package.
            relative_path: Relative path to the file within the package.

        Returns:
            File content as bytes.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        s3_key = f"{s3_path.rstrip('/')}/{safe_package_path(relative_path)}"

        try:
            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=s3_key,
            )
            return response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"File not found: {relative_path}") from e
            raise

    async def list_files(self, s3_path: str) -> list[FileInfo]:
        """List all files in a skill package.

        Args:
            s3_path: S3 prefix for the skill package.

        Returns:
            List of FileInfo objects for each file.
        """
        files = []
        prefix = s3_path.rstrip("/") + "/"

        paginator = self.client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Extract relative path
                relative_path = key[len(prefix) :]
                if relative_path:
                    files.append(
                        FileInfo(
                            path=relative_path,
                            size=obj["Size"],
                            content_type=self._guess_content_type(relative_path),
                        )
                    )

        return files

    async def delete_package(self, s3_path: str) -> int:
        """Delete all files in a skill package.

        Args:
            s3_path: S3 prefix for the skill package.

        Returns:
            Number of files deleted.
        """
        prefix = s3_path.rstrip("/") + "/"
        deleted_count = 0

        paginator = self.client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue

            # Delete in batches of 1000 (S3 limit)
            delete_keys = [{"Key": obj["Key"]} for obj in objects]
            self.client.delete_objects(
                Bucket=self.bucket_name,
                Delete={"Objects": delete_keys},
            )
            deleted_count += len(delete_keys)

        logger.info(f"Deleted {deleted_count} files from {s3_path}")
        return deleted_count

    async def package_exists(self, s3_path: str) -> bool:
        """Check if a skill package exists in S3.

        Args:
            s3_path: S3 prefix for the skill package.

        Returns:
            True if the package exists (has at least one file).
        """
        prefix = s3_path.rstrip("/") + "/"

        response = self.client.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=prefix,
            MaxKeys=1,
        )

        return response.get("KeyCount", 0) > 0

    def _detect_root_folder(self, paths: list[str]) -> str | None:
        """Detect a common root folder in a list of paths.

        GitHub ZIP downloads typically have a root folder like 'repo-main/'.

        Args:
            paths: List of file paths.

        Returns:
            Root folder with trailing slash, or None if no common root.
        """
        non_dir_paths = [p for p in paths if not p.endswith("/") and not p.startswith("__MACOSX")]
        if not non_dir_paths:
            return None

        # Check if all paths share a common first directory
        first_dirs = set()
        has_top_level_file = False
        for path in non_dir_paths:
            parts = path.split("/")
            if len(parts) > 1:
                first_dirs.add(parts[0])
            else:
                # File at top level means no common root folder
                has_top_level_file = True

        # If there's a top-level file, there can't be a common root folder
        if has_top_level_file:
            return None

        if len(first_dirs) == 1:
            return first_dirs.pop() + "/"

        return None

    def _should_skip_file(self, filename: str) -> bool:
        """Check if a file should be skipped during extraction.

        Args:
            filename: The filename to check.

        Returns:
            True if the file should be skipped.
        """
        # Skip macOS metadata
        if filename.startswith("__MACOSX"):
            return True

        # Skip hidden files
        if "/." in filename or filename.startswith("."):
            return True

        return False

    def _guess_content_type(self, filename: str) -> str:
        """Guess the content type for a file.

        Args:
            filename: The filename.

        Returns:
            Content type string.
        """
        import mimetypes

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        defaults = {
            "md": "text/markdown",
            "yaml": "application/yaml",
            "yml": "application/yaml",
            "json": "application/json",
            "txt": "text/plain",
        }

        if ext in defaults:
            return defaults[ext]

        content_type, _ = mimetypes.guess_type(filename)
        if content_type:
            return content_type

        return "application/octet-stream"
