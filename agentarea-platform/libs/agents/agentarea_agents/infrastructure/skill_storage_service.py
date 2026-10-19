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
# Immutable packages of catalog skills, keyed by the digest of their files.
# Shared by every workspace: what is stored here is public catalog content,
# and no tenant edit ever writes under it (an edit copies into the tenant's
# own prefix first).
CATALOG_PREFIX = f"{SKILLS_PREFIX}/catalog"
GITHUB_TREE_ALIASES = f"{CATALOG_PREFIX}/github-tree"


def tenant_package_prefix(workspace_id: str, skill_id: str) -> str:
    """The prefix a workspace's own copy of a skill lives under."""
    return f"{SKILLS_PREFIX}/{workspace_id}/{skill_id}/"


def is_catalog_package(s3_path: str | None) -> bool:
    return bool(s3_path) and str(s3_path).startswith(f"{CATALOG_PREFIX}/")


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


@dataclass
class FileInfo:
    """Information about a stored file."""

    path: str
    size: int
    content_type: str | None = None


class SkillStorageService:
    """Service for storing skill packages in S3.

    A workspace's own skill is stored at s3://{bucket}/skills/{workspace_id}/{skill_id}/;
    a catalog skill's package at s3://{bucket}/skills/catalog/{sha256}/.
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

    async def store_catalog_package(self, files: Mapping[str, bytes]) -> str:
        """Store a catalog package under its digest, once; return its prefix.

        A prefix already holding every path is reused as is: the key is the
        digest, so the same paths there are the same bytes. One holding only
        some of them (an earlier store that died midway) is completed.
        """
        checked = checked_package_files(files)
        prefix = f"{CATALOG_PREFIX}/{package_digest(checked)}/"
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
            logger.info("Stored catalog skill package %s (%d files)", prefix, len(missing))
        return prefix

    async def store_package_files(
        self, skill_id: str, workspace_id: str, files: Mapping[str, bytes]
    ) -> str:
        """Write a file set into a workspace's own copy of a skill; return its prefix."""
        checked = checked_package_files(files)
        prefix = self._get_s3_prefix(workspace_id, skill_id)
        for path, data in checked.items():
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"{prefix}{path}",
                Body=data,
                ContentType=self._guess_content_type(path),
            )
        return prefix

    async def read_package(self, s3_path: str) -> dict[str, bytes]:
        """Every file of a package, by relative path."""
        return {
            info.path: await self.get_file_content(s3_path, info.path)
            for info in await self.list_files(s3_path)
        }

    async def get_github_tree_package(self, tree_sha: str) -> str | None:
        """The catalog package a GitHub tree was stored as, if it was."""
        try:
            response = self.client.get_object(
                Bucket=self.bucket_name, Key=f"{GITHUB_TREE_ALIASES}/{tree_sha}"
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise
        return response["Body"].read().decode("utf-8")

    async def put_github_tree_package(self, tree_sha: str, s3_path: str) -> None:
        """Record which catalog package a GitHub tree is, so it is fetched once."""
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=f"{GITHUB_TREE_ALIASES}/{tree_sha}",
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

    def validate_package_zip(self, zip_data: bytes | BinaryIO) -> None:
        """Refuse a package ``store_package_from_zip`` would refuse, storing nothing.

        Lets a caller check the whole package before it creates the row the
        package belongs to.

        Raises:
            ValueError: If the data is not a ZIP archive, is over budget, or
                holds a path that is not a plain relative package path.
        """
        if isinstance(zip_data, bytes):
            zip_data = io.BytesIO(zip_data)
        zip_data.seek(0)
        try:
            with zipfile.ZipFile(zip_data, "r") as zf:
                self._package_entries(zf)
        except zipfile.BadZipFile as e:
            raise ValueError("Skill package is not a valid ZIP archive") from e
        finally:
            zip_data.seek(0)

    async def store_package_from_zip(
        self,
        skill_id: str,
        workspace_id: str,
        zip_data: bytes | BinaryIO,
    ) -> str:
        """Store a skill package from a ZIP file.

        Every path and the size budget are checked before the first upload.

        Args:
            skill_id: The skill ID.
            workspace_id: The workspace ID.
            zip_data: ZIP file as bytes or file-like object.

        Returns:
            S3 path prefix for the stored package.
        """
        if isinstance(zip_data, bytes):
            zip_data = io.BytesIO(zip_data)

        s3_prefix = self._get_s3_prefix(workspace_id, skill_id)

        try:
            zf = zipfile.ZipFile(zip_data, "r")
        except zipfile.BadZipFile as e:
            raise ValueError("Skill package is not a valid ZIP archive") from e
        with zf:
            for info, relative_path in self._package_entries(zf):
                content = read_entry(zf, info)

                # Upload to S3
                s3_key = f"{s3_prefix}{relative_path}"
                content_type = self._guess_content_type(relative_path)

                self.client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=content,
                    ContentType=content_type,
                )

                logger.debug(f"Uploaded {relative_path} to s3://{self.bucket_name}/{s3_key}")

        return s3_prefix

    async def store_package_from_directory(
        self,
        skill_id: str,
        workspace_id: str,
        directory: str | Path,
    ) -> str:
        """Store a skill package from a local directory.

        Args:
            skill_id: The skill ID.
            workspace_id: The workspace ID.
            directory: Path to the directory.

        Returns:
            S3 path prefix for the stored package.
        """
        directory = Path(directory)
        s3_prefix = self._get_s3_prefix(workspace_id, skill_id)

        for file_path in directory.rglob("*"):
            if file_path.is_dir():
                continue

            # Skip hidden files
            if any(part.startswith(".") for part in file_path.parts):
                continue

            relative_path = str(file_path.relative_to(directory)).replace("\\", "/")
            s3_key = f"{s3_prefix}{relative_path}"

            content_type = self._guess_content_type(relative_path)

            with open(file_path, "rb") as f:
                self.client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=f.read(),
                    ContentType=content_type,
                )

            logger.debug(f"Uploaded {relative_path} to s3://{self.bucket_name}/{s3_key}")

        return s3_prefix

    async def store_single_file(
        self,
        skill_id: str,
        workspace_id: str,
        filename: str,
        content: bytes | str,
    ) -> str:
        """Store a single file for a skill.

        Args:
            skill_id: The skill ID.
            workspace_id: The workspace ID.
            filename: The filename to store.
            content: File content as bytes or string.

        Returns:
            S3 path prefix for the stored file.
        """
        s3_prefix = self._get_s3_prefix(workspace_id, skill_id)
        s3_key = f"{s3_prefix}{safe_package_path(filename)}"

        if isinstance(content, str):
            content = content.encode("utf-8")

        content_type = self._guess_content_type(filename)

        self.client.put_object(
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=content,
            ContentType=content_type,
        )

        return s3_prefix

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
