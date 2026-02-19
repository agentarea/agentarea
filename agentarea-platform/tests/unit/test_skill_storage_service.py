"""Unit tests for SkillStorageService with mocked S3."""

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from agentarea_agents.infrastructure.skill_storage_service import (
    FileInfo,
    SkillStorageService,
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
    settings.S3_BUCKET_NAME = "test-bucket"
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


class TestStorePackageFromZip:
    """Tests for store_package_from_zip method."""

    @pytest.mark.asyncio
    async def test_store_simple_zip(self, storage_service, mock_s3_client):
        """Test storing a simple ZIP with flat structure."""
        zip_data = create_test_zip({
            "SKILL.md": "# Test Skill\nContent here",
            "template.txt": "Template content",
        })

        s3_path = await storage_service.store_package_from_zip(
            skill_id="skill-123",
            workspace_id="ws-456",
            zip_data=zip_data,
        )

        assert s3_path == "skills/ws-456/skill-123/"
        assert mock_s3_client.put_object.call_count == 2

        # Check that files were uploaded with correct keys
        call_args_list = mock_s3_client.put_object.call_args_list
        uploaded_keys = [call.kwargs["Key"] for call in call_args_list]
        assert "skills/ws-456/skill-123/SKILL.md" in uploaded_keys
        assert "skills/ws-456/skill-123/template.txt" in uploaded_keys

    @pytest.mark.asyncio
    async def test_store_zip_with_github_root_folder(self, storage_service, mock_s3_client):
        """Test storing a GitHub-style ZIP with root folder."""
        zip_data = create_test_zip({
            "repo-main/SKILL.md": "# Test Skill",
            "repo-main/templates/example.txt": "Example",
            "repo-main/README.md": "Readme",
        })

        s3_path = await storage_service.store_package_from_zip(
            skill_id="skill-123",
            workspace_id="ws-456",
            zip_data=zip_data,
        )

        assert s3_path == "skills/ws-456/skill-123/"
        assert mock_s3_client.put_object.call_count == 3

        # Root folder should be stripped
        call_args_list = mock_s3_client.put_object.call_args_list
        uploaded_keys = [call.kwargs["Key"] for call in call_args_list]
        assert "skills/ws-456/skill-123/SKILL.md" in uploaded_keys
        assert "skills/ws-456/skill-123/templates/example.txt" in uploaded_keys
        assert "skills/ws-456/skill-123/README.md" in uploaded_keys

    @pytest.mark.asyncio
    async def test_store_zip_skips_macosx_files(self, storage_service, mock_s3_client):
        """Test that __MACOSX files are skipped."""
        zip_data = create_test_zip({
            "SKILL.md": "# Test Skill",
            "__MACOSX/._SKILL.md": "metadata",
            "__MACOSX/.DS_Store": "more metadata",
        })

        await storage_service.store_package_from_zip(
            skill_id="skill-123",
            workspace_id="ws-456",
            zip_data=zip_data,
        )

        # Only SKILL.md should be uploaded
        assert mock_s3_client.put_object.call_count == 1
        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        assert "SKILL.md" in call_kwargs["Key"]

    @pytest.mark.asyncio
    async def test_store_zip_skips_hidden_files(self, storage_service, mock_s3_client):
        """Test that hidden files are skipped."""
        zip_data = create_test_zip({
            "SKILL.md": "# Test Skill",
            ".gitignore": "*.pyc",
            ".env": "SECRET=value",
            "templates/.hidden": "hidden",
        })

        await storage_service.store_package_from_zip(
            skill_id="skill-123",
            workspace_id="ws-456",
            zip_data=zip_data,
        )

        # Only SKILL.md should be uploaded
        assert mock_s3_client.put_object.call_count == 1

    @pytest.mark.asyncio
    async def test_store_zip_with_bytes(self, storage_service, mock_s3_client):
        """Test storing ZIP provided as bytes."""
        zip_buffer = create_test_zip({"SKILL.md": "# Test"})
        zip_bytes = zip_buffer.read()

        s3_path = await storage_service.store_package_from_zip(
            skill_id="skill-123",
            workspace_id="ws-456",
            zip_data=zip_bytes,
        )

        assert s3_path == "skills/ws-456/skill-123/"
        assert mock_s3_client.put_object.call_count == 1

    @pytest.mark.asyncio
    async def test_store_zip_content_types(self, storage_service, mock_s3_client):
        """Test that correct content types are set."""
        zip_data = create_test_zip({
            "SKILL.md": "# Markdown",
            "config.json": "{}",
            "data.yaml": "key: value",
        })

        await storage_service.store_package_from_zip(
            skill_id="skill-123",
            workspace_id="ws-456",
            zip_data=zip_data,
        )

        call_args_list = mock_s3_client.put_object.call_args_list
        content_types = {}
        for call in call_args_list:
            key = call.kwargs["Key"].split("/")[-1]
            content_types[key] = call.kwargs["ContentType"]

        assert content_types["SKILL.md"] == "text/markdown"
        assert content_types["config.json"] == "application/json"
        assert content_types["data.yaml"] == "application/yaml"


class TestStorePackageFromDirectory:
    """Tests for store_package_from_directory method."""

    @pytest.mark.asyncio
    async def test_store_directory(self, storage_service, mock_s3_client, tmp_path):
        """Test storing a directory."""
        # Create test directory structure
        (tmp_path / "SKILL.md").write_text("# Test Skill")
        (tmp_path / "templates").mkdir()
        (tmp_path / "templates" / "example.txt").write_text("Example")

        s3_path = await storage_service.store_package_from_directory(
            skill_id="skill-123",
            workspace_id="ws-456",
            directory=tmp_path,
        )

        assert s3_path == "skills/ws-456/skill-123/"
        assert mock_s3_client.put_object.call_count == 2

    @pytest.mark.asyncio
    async def test_store_directory_skips_hidden(self, storage_service, mock_s3_client, tmp_path):
        """Test that hidden files in directories are skipped."""
        (tmp_path / "SKILL.md").write_text("# Test Skill")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git config")
        (tmp_path / ".env").write_text("SECRET=value")

        await storage_service.store_package_from_directory(
            skill_id="skill-123",
            workspace_id="ws-456",
            directory=tmp_path,
        )

        # Only SKILL.md should be uploaded
        assert mock_s3_client.put_object.call_count == 1


class TestStoreSingleFile:
    """Tests for store_single_file method."""

    @pytest.mark.asyncio
    async def test_store_single_file_bytes(self, storage_service, mock_s3_client):
        """Test storing a single file as bytes."""
        content = b"# Test Skill Content"

        s3_path = await storage_service.store_single_file(
            skill_id="skill-123",
            workspace_id="ws-456",
            filename="SKILL.md",
            content=content,
        )

        assert s3_path == "skills/ws-456/skill-123/"
        mock_s3_client.put_object.assert_called_once()
        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        assert call_kwargs["Key"] == "skills/ws-456/skill-123/SKILL.md"
        assert call_kwargs["Body"] == content

    @pytest.mark.asyncio
    async def test_store_single_file_string(self, storage_service, mock_s3_client):
        """Test storing a single file as string."""
        content = "# Test Skill Content"

        await storage_service.store_single_file(
            skill_id="skill-123",
            workspace_id="ws-456",
            filename="SKILL.md",
            content=content,
        )

        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        assert call_kwargs["Body"] == content.encode("utf-8")


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
