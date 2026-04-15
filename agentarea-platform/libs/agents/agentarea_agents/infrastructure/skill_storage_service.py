"""Skill storage service for S3 operations."""

import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from agentarea_common.config.aws import get_aws_settings, get_s3_client
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Information about a stored file."""

    path: str
    size: int
    content_type: str | None = None


class SkillStorageService:
    """Service for storing skill packages in S3.

    Skills are stored at: s3://{bucket}/skills/{workspace_id}/{skill_id}/
    """

    SKILLS_PREFIX = "skills"

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
        """Get the S3 bucket name."""
        return self.settings.S3_BUCKET_NAME

    def _get_s3_prefix(self, workspace_id: str, skill_id: str) -> str:
        """Get the S3 prefix for a skill package.

        Args:
            workspace_id: The workspace ID.
            skill_id: The skill ID.

        Returns:
            S3 key prefix: skills/{workspace_id}/{skill_id}/
        """
        return f"{self.SKILLS_PREFIX}/{workspace_id}/{skill_id}/"

    async def store_package_from_zip(
        self,
        skill_id: str,
        workspace_id: str,
        zip_data: bytes | BinaryIO,
    ) -> str:
        """Store a skill package from a ZIP file.

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

        with zipfile.ZipFile(zip_data, "r") as zf:
            # Detect common root folder (GitHub style)
            root_folder = self._detect_root_folder(zf.namelist())

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

                # Read file content
                content = zf.read(info.filename)

                # Upload to S3
                s3_key = f"{s3_prefix}{relative_path}"
                content_type = self._guess_content_type(relative_path)

                self.client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=content,
                    ContentType=content_type,
                )

                logger.debug("Uploaded file to S3", extra={"relative_path": relative_path, "bucket": self.bucket_name, "s3_key": s3_key})

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

            logger.debug("Uploaded file to S3", extra={"relative_path": relative_path, "bucket": self.bucket_name, "s3_key": s3_key})

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
        s3_key = f"{s3_prefix}{filename}"

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
        s3_key = f"{s3_path.rstrip('/')}/{relative_path.lstrip('/')}"

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
        s3_key = f"{s3_path.rstrip('/')}/{relative_path.lstrip('/')}"

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

        logger.info("Deleted files from S3", extra={"deleted_count": deleted_count, "s3_path": s3_path})
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
