"""Unit tests for SkillStorageService with mocked S3."""

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from agentarea_agents.infrastructure.skill_storage_service import (
    SkillStorageService,
    package_digest,
)


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 client."""
    client = MagicMock()
    # Default paginator behavior
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": []}]
    client.get_paginator.return_value = paginator
    return client


@pytest.fixture
def mock_aws_settings():
    """Create mock AWS settings."""
    settings = MagicMock()
    settings.ARTIFACTS_BUCKET = "test-bucket"
    return settings


@pytest.fixture
def storage_service(mock_s3_client, mock_aws_settings):
    """Create a SkillStorageService with mocked dependencies."""
    with patch(
        "agentarea_agents.infrastructure.skill_storage_service.get_s3_client",
        return_value=mock_s3_client,
    ), patch(
        "agentarea_agents.infrastructure.skill_storage_service.get_aws_settings",
        return_value=mock_aws_settings,
    ):
        service = SkillStorageService()
        # Force lazy-loading
        _ = service.client
        _ = service.settings
        return service


def create_test_zip(files: dict[str, bytes | str]) -> io.BytesIO:
    """Create a test ZIP file in memory.

    Args:
        files: Dictionary of filename -> content

    Returns:
        BytesIO containing the ZIP data
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(filename, content)
    buffer.seek(0)
    return buffer


class TestFilesFromZip:
    """A ZIP upload becomes a file set; nothing is stored until it is a package."""

    def test_a_flat_zip(self, storage_service, mock_s3_client):
        zip_data = create_test_zip({"SKILL.md": "# Test Skill", "template.txt": "Template"})

        files = storage_service.files_from_zip(zip_data)

        assert files == {"SKILL.md": b"# Test Skill", "template.txt": b"Template"}
        mock_s3_client.put_object.assert_not_called()

    def test_a_github_root_folder_is_stripped(self, storage_service):
        zip_data = create_test_zip(
            {
                "repo-main/SKILL.md": "# Test Skill",
                "repo-main/templates/example.txt": "Example",
            }
        )

        assert set(storage_service.files_from_zip(zip_data)) == {
            "SKILL.md",
            "templates/example.txt",
        }

    def test_macos_metadata_and_hidden_files_are_left_out(self, storage_service):
        zip_data = create_test_zip(
            {
                "SKILL.md": "# Test Skill",
                "__MACOSX/._SKILL.md": "metadata",
                ".env": "SECRET=value",
                "templates/.hidden": "hidden",
            }
        )

        assert set(storage_service.files_from_zip(zip_data)) == {"SKILL.md"}

    def test_bytes_are_accepted(self, storage_service):
        assert storage_service.files_from_zip(create_test_zip({"SKILL.md": "# T"}).read()) == {
            "SKILL.md": b"# T"
        }

    def test_not_a_zip_is_refused(self, storage_service):
        with pytest.raises(ValueError, match="ZIP"):
            storage_service.files_from_zip(b"not a zip")


class TestFilesFromDirectory:
    def test_hidden_files_are_left_out(self, tmp_path):
        (tmp_path / "SKILL.md").write_text("# Test Skill")
        (tmp_path / "templates").mkdir()
        (tmp_path / "templates" / "example.txt").write_text("Example")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git config")

        assert SkillStorageService.files_from_directory(tmp_path) == {
            "SKILL.md": b"# Test Skill",
            "templates/example.txt": b"Example",
        }


class TestStoreWorkspacePackage:
    """A workspace's own package lives under its digest, in the workspace's prefix."""

    @pytest.mark.asyncio
    async def test_a_package_is_stored_under_its_digest(self, storage_service, mock_s3_client):
        files = {"SKILL.md": b"# Markdown", "config.json": b"{}"}

        s3_path = await storage_service.store_workspace_package(files, "ws-456")

        assert s3_path == f"skills/ws-456/packages/{package_digest(files)}/"
        content_types = {
            call.kwargs["Key"].rsplit("/", 1)[-1]: call.kwargs["ContentType"]
            for call in mock_s3_client.put_object.call_args_list
        }
        assert content_types == {"SKILL.md": "text/markdown", "config.json": "application/json"}

    @pytest.mark.asyncio
    async def test_the_same_files_are_the_same_package(self, storage_service):
        files = {"SKILL.md": b"# Same"}

        first = await storage_service.store_workspace_package(files, "ws-456")
        again = await storage_service.store_workspace_package(dict(files), "ws-456")

        assert first == again


class TestGetFileUrl:
    """Tests for get_file_url method."""

    @pytest.mark.asyncio
    async def test_get_file_url(self, storage_service, mock_s3_client):
        """Test generating a presigned URL."""
        mock_s3_client.generate_presigned_url.return_value = "https://s3.example.com/presigned"

        url = await storage_service.get_file_url(
            s3_path="skills/ws-456/skill-123/",
            relative_path="SKILL.md",
            expires_in=3600,
        )

        assert url == "https://s3.example.com/presigned"
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "test-bucket",
                "Key": "skills/ws-456/skill-123/SKILL.md",
            },
            ExpiresIn=3600,
        )

    @pytest.mark.asyncio
    async def test_get_file_url_normalizes_slashes(self, storage_service, mock_s3_client):
        """Test that slashes in paths are normalized."""
        mock_s3_client.generate_presigned_url.return_value = "https://example.com"

        await storage_service.get_file_url(
            s3_path="skills/ws-456/skill-123",  # No trailing slash
            relative_path="/templates/example.txt",  # Leading slash
        )

        call_kwargs = mock_s3_client.generate_presigned_url.call_args.kwargs
        assert call_kwargs["Params"]["Key"] == "skills/ws-456/skill-123/templates/example.txt"


class TestGetFileContent:
    """Tests for get_file_content method."""

    @pytest.mark.asyncio
    async def test_get_file_content(self, storage_service, mock_s3_client):
        """Test getting file content."""
        mock_body = MagicMock()
        mock_body.read.return_value = b"# File content"
        mock_s3_client.get_object.return_value = {"Body": mock_body}

        content = await storage_service.get_file_content(
            s3_path="skills/ws-456/skill-123/",
            relative_path="SKILL.md",
        )

        assert content == b"# File content"
        mock_s3_client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="skills/ws-456/skill-123/SKILL.md",
        )

    @pytest.mark.asyncio
    async def test_get_file_content_not_found(self, storage_service, mock_s3_client):
        """Test FileNotFoundError for missing file."""
        from botocore.exceptions import ClientError

        mock_s3_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )

        with pytest.raises(FileNotFoundError, match="File not found"):
            await storage_service.get_file_content(
                s3_path="skills/ws-456/skill-123/",
                relative_path="nonexistent.md",
            )


class TestListFiles:
    """Tests for list_files method."""

    @pytest.mark.asyncio
    async def test_list_files(self, storage_service, mock_s3_client):
        """Test listing files in a package."""
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "skills/ws-456/skill-123/SKILL.md", "Size": 100},
                    {"Key": "skills/ws-456/skill-123/templates/example.txt", "Size": 50},
                ]
            }
        ]
        mock_s3_client.get_paginator.return_value = paginator

        files = await storage_service.list_files("skills/ws-456/skill-123/")

        assert len(files) == 2
        assert files[0].path == "SKILL.md"
        assert files[0].size == 100
        assert files[1].path == "templates/example.txt"
        assert files[1].size == 50

    @pytest.mark.asyncio
    async def test_list_files_empty(self, storage_service, mock_s3_client):
        """Test listing files for empty package."""
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": []}]
        mock_s3_client.get_paginator.return_value = paginator

        files = await storage_service.list_files("skills/ws-456/skill-123/")

        assert len(files) == 0

    @pytest.mark.asyncio
    async def test_list_files_pagination(self, storage_service, mock_s3_client):
        """Test listing files with pagination."""
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "skills/ws-456/skill-123/file1.md", "Size": 10}]},
            {"Contents": [{"Key": "skills/ws-456/skill-123/file2.md", "Size": 20}]},
        ]
        mock_s3_client.get_paginator.return_value = paginator

        files = await storage_service.list_files("skills/ws-456/skill-123/")

        assert len(files) == 2


class TestDeletePackage:
    """Tests for delete_package method."""

    @pytest.mark.asyncio
    async def test_delete_package(self, storage_service, mock_s3_client):
        """Test deleting a package."""
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "skills/ws-456/skill-123/SKILL.md"},
                    {"Key": "skills/ws-456/skill-123/template.txt"},
                ]
            }
        ]
        mock_s3_client.get_paginator.return_value = paginator

        deleted_count = await storage_service.delete_package("skills/ws-456/skill-123/")

        assert deleted_count == 2
        mock_s3_client.delete_objects.assert_called_once()
        call_kwargs = mock_s3_client.delete_objects.call_args.kwargs
        assert len(call_kwargs["Delete"]["Objects"]) == 2

    @pytest.mark.asyncio
    async def test_delete_empty_package(self, storage_service, mock_s3_client):
        """Test deleting an empty package."""
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": []}]
        mock_s3_client.get_paginator.return_value = paginator

        deleted_count = await storage_service.delete_package("skills/ws-456/skill-123/")

        assert deleted_count == 0
        mock_s3_client.delete_objects.assert_not_called()


class TestPackageExists:
    """Tests for package_exists method."""

    @pytest.mark.asyncio
    async def test_package_exists_true(self, storage_service, mock_s3_client):
        """Test package exists returns True."""
        mock_s3_client.list_objects_v2.return_value = {"KeyCount": 1}

        exists = await storage_service.package_exists("skills/ws-456/skill-123/")

        assert exists is True

    @pytest.mark.asyncio
    async def test_package_exists_false(self, storage_service, mock_s3_client):
        """Test package exists returns False."""
        mock_s3_client.list_objects_v2.return_value = {"KeyCount": 0}

        exists = await storage_service.package_exists("skills/ws-456/skill-123/")

        assert exists is False


class TestHelperMethods:
    """Tests for helper methods."""

    def test_detect_root_folder_with_github_style(self, storage_service):
        """Test detecting GitHub-style root folder."""
        paths = [
            "my-repo-main/SKILL.md",
            "my-repo-main/templates/example.txt",
            "my-repo-main/",
        ]

        result = storage_service._detect_root_folder(paths)

        assert result == "my-repo-main/"

    def test_detect_root_folder_no_common_root(self, storage_service):
        """Test when there's no common root folder."""
        paths = [
            "SKILL.md",
            "templates/example.txt",
        ]

        result = storage_service._detect_root_folder(paths)

        assert result is None

    def test_detect_root_folder_mixed_roots(self, storage_service):
        """Test when there are multiple root folders."""
        paths = [
            "folder1/file1.md",
            "folder2/file2.md",
        ]

        result = storage_service._detect_root_folder(paths)

        assert result is None

    def test_should_skip_file_macosx(self, storage_service):
        """Test skipping __MACOSX files."""
        assert storage_service._should_skip_file("__MACOSX/._SKILL.md") is True
        assert storage_service._should_skip_file("__MACOSX/.DS_Store") is True

    def test_should_skip_file_hidden(self, storage_service):
        """Test skipping hidden files."""
        assert storage_service._should_skip_file(".gitignore") is True
        assert storage_service._should_skip_file(".env") is True
        assert storage_service._should_skip_file("folder/.hidden") is True

    def test_should_skip_file_normal(self, storage_service):
        """Test not skipping normal files."""
        assert storage_service._should_skip_file("SKILL.md") is False
        assert storage_service._should_skip_file("templates/example.txt") is False

    def test_guess_content_type_markdown(self, storage_service):
        """Test content type guessing for markdown."""
        assert storage_service._guess_content_type("SKILL.md") == "text/markdown"
        assert storage_service._guess_content_type("README.md") == "text/markdown"

    def test_guess_content_type_json(self, storage_service):
        """Test content type guessing for JSON."""
        assert storage_service._guess_content_type("config.json") == "application/json"

    def test_guess_content_type_yaml(self, storage_service):
        """Test content type guessing for YAML."""
        assert storage_service._guess_content_type("config.yaml") == "application/yaml"
        assert storage_service._guess_content_type("config.yml") == "application/yaml"

    def test_guess_content_type_unknown(self, storage_service):
        """Test content type guessing for unknown types."""
        assert storage_service._guess_content_type("file.unknown") == "application/octet-stream"
