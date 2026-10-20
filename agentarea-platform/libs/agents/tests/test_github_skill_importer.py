"""Unit tests for GitHubSkillImporter with mocked HTTP responses."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubInvalidURLError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubRepoInfo,
    GitHubSkillImporter,
    GitHubSkillImporterError,
)


class TestParseGitHubUrl:
    """Tests for parse_github_url method."""

    def test_parse_simple_https_url(self):
        """Test parsing simple HTTPS URL."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url("https://github.com/owner/repo")

        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.branch is None
        assert result.path is None

    def test_parse_https_url_with_git_suffix(self):
        """Test parsing HTTPS URL with .git suffix."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url("https://github.com/owner/repo.git")

        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_parse_https_url_with_branch(self):
        """Test parsing HTTPS URL with branch."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url("https://github.com/owner/repo/tree/main")

        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.branch == "main"
        assert result.path is None

    def test_parse_https_url_with_branch_and_path(self):
        """Test parsing HTTPS URL with branch and subdirectory path."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url(
            "https://github.com/owner/repo/tree/develop/skills/my-skill"
        )

        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.branch == "develop"
        assert result.path == "skills/my-skill"

    def test_parse_https_url_with_blob(self):
        """Test parsing HTTPS URL with blob (file path)."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url("https://github.com/owner/repo/blob/main/README.md")

        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.branch == "main"
        assert result.path == "README.md"

    def test_parse_ssh_url(self):
        """Test parsing SSH URL."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url("git@github.com:owner/repo.git")

        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.branch is None

    def test_parse_ssh_url_without_git_suffix(self):
        """Test parsing SSH URL without .git suffix."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url("git@github.com:owner/repo")

        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_parse_url_with_www(self):
        """Test parsing URL with www prefix."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url("https://www.github.com/owner/repo")

        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_parse_url_with_trailing_slash(self):
        """Test parsing URL with trailing slash."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url("https://github.com/owner/repo/")

        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_parse_url_with_whitespace(self):
        """Test parsing URL with leading/trailing whitespace."""
        importer = GitHubSkillImporter()
        result = importer.parse_github_url("  https://github.com/owner/repo  ")

        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_parse_invalid_url_not_github(self):
        """Test parsing non-GitHub URL raises error."""
        importer = GitHubSkillImporter()

        with pytest.raises(GitHubInvalidURLError, match="Not a GitHub URL"):
            importer.parse_github_url("https://gitlab.com/owner/repo")

    def test_parse_invalid_url_missing_repo(self):
        """Test parsing URL with missing repo raises error."""
        importer = GitHubSkillImporter()

        with pytest.raises(GitHubInvalidURLError, match="Invalid GitHub repository URL"):
            importer.parse_github_url("https://github.com/owner")

    def test_parse_invalid_url_empty(self):
        """Test parsing empty URL raises error."""
        importer = GitHubSkillImporter()

        with pytest.raises(GitHubInvalidURLError):
            importer.parse_github_url("")


class TestDownloadRepo:
    """download_repo: codeload without a token, the API zipball with one."""

    @staticmethod
    def _importer(monkeypatch, handler, token=None):
        from agentarea_agents.infrastructure import github_skill_importer as module

        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        def client(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(record), **kwargs)

        monkeypatch.setattr(module, "safe_async_client", client)
        importer = GitHubSkillImporter(github_token=token, transport=httpx.MockTransport(record))
        return importer, seen

    @pytest.mark.asyncio
    async def test_download_repo_success(self, monkeypatch):
        importer, seen = self._importer(monkeypatch, lambda _r: httpx.Response(200, content=b"PK"))

        assert await importer.download_repo("https://github.com/owner/repo") == b"PK"
        assert [str(r.url) for r in seen] == ["https://codeload.github.com/owner/repo/zip/HEAD"]

    @pytest.mark.asyncio
    async def test_download_repo_with_branch(self, monkeypatch):
        importer, seen = self._importer(monkeypatch, lambda _r: httpx.Response(200, content=b"PK"))

        await importer.download_repo("https://github.com/owner/repo/tree/develop")

        assert str(seen[0].url).endswith("/zip/develop")

    @pytest.mark.asyncio
    async def test_download_repo_with_token(self, monkeypatch):
        importer, seen = self._importer(
            monkeypatch, lambda _r: httpx.Response(200, content=b"PK"), token="test-token"
        )

        await importer.download_repo("https://github.com/owner/repo/tree/main")

        assert str(seen[0].url) == "https://api.github.com/repos/owner/repo/zipball/main"
        assert seen[0].headers["Authorization"] == "Bearer test-token"

    @pytest.mark.asyncio
    async def test_download_repo_rate_limit_error(self, monkeypatch):
        limited = httpx.Response(
            403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1"}, text="limit"
        )
        importer, _ = self._importer(monkeypatch, lambda _r: limited, token="t")

        with pytest.raises(GitHubRateLimitError, match="rate limit exceeded"):
            await importer.download_repo("https://github.com/owner/repo/tree/main")

    @pytest.mark.asyncio
    async def test_download_repo_throttled_without_a_token(self, monkeypatch):
        importer, _ = self._importer(monkeypatch, lambda _r: httpx.Response(429))

        with pytest.raises(GitHubRateLimitError):
            await importer.download_repo("https://github.com/owner/repo")

    @pytest.mark.asyncio
    async def test_download_repo_not_found_error(self, monkeypatch):
        importer, _ = self._importer(monkeypatch, lambda _r: httpx.Response(404, text="Not Found"))

        with pytest.raises(GitHubNotFoundError, match="not found"):
            await importer.download_repo("https://github.com/owner/repo")

    @pytest.mark.asyncio
    async def test_download_repo_auth_error(self, monkeypatch):
        importer, _ = self._importer(
            monkeypatch, lambda _r: httpx.Response(401, text="Bad credentials"), token="bad"
        )

        with pytest.raises(GitHubSkillImporterError, match="Authentication failed"):
            await importer.download_repo("https://github.com/owner/repo/tree/main")

    @pytest.mark.asyncio
    async def test_download_repo_timeout_error(self, monkeypatch):
        def timeout(request):
            raise httpx.ReadTimeout("slow", request=request)

        importer, _ = self._importer(monkeypatch, timeout)

        with pytest.raises(GitHubSkillImporterError, match="Timeout"):
            await importer.download_repo("https://github.com/owner/repo")

    @pytest.mark.asyncio
    async def test_download_repo_connection_error(self, monkeypatch):
        def refused(request):
            raise httpx.ConnectError("refused", request=request)

        importer, _ = self._importer(monkeypatch, refused)

        with pytest.raises(GitHubSkillImporterError, match="Error downloading"):
            await importer.download_repo("https://github.com/owner/repo")


class TestGetDefaultBranch:
    """Tests for _get_default_branch method."""

    @pytest.mark.asyncio
    async def test_get_default_branch_main(self):
        """Test getting default branch when it's main."""
        importer = GitHubSkillImporter()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"default_branch": "main"}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await importer._get_default_branch("owner", "repo")

            assert result == "main"

    @pytest.mark.asyncio
    async def test_get_default_branch_master(self):
        """Test getting default branch when it's master."""
        importer = GitHubSkillImporter()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"default_branch": "master"}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await importer._get_default_branch("owner", "repo")

            assert result == "master"

    @pytest.mark.asyncio
    async def test_get_default_branch_fallback(self):
        """Test fallback to 'main' when not specified."""
        importer = GitHubSkillImporter()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {}  # No default_branch field
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await importer._get_default_branch("owner", "repo")

            assert result == "main"


class TestGetRepoInfo:
    """Tests for get_repo_info method."""

    @pytest.mark.asyncio
    async def test_get_repo_info_success(self):
        """Test getting repository info."""
        importer = GitHubSkillImporter()

        repo_data = {
            "name": "repo",
            "full_name": "owner/repo",
            "description": "Test repository",
            "default_branch": "main",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = repo_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await importer.get_repo_info("https://github.com/owner/repo")

            assert result["name"] == "repo"
            assert result["full_name"] == "owner/repo"

    @pytest.mark.asyncio
    async def test_get_repo_info_not_found(self):
        """Test getting info for non-existent repo."""
        importer = GitHubSkillImporter()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = "Not Found"
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(GitHubNotFoundError):
                await importer.get_repo_info("https://github.com/owner/nonexistent")


class TestHeaders:
    """Tests for header generation."""

    def test_headers_without_token(self):
        """Test headers without authentication token."""
        importer = GitHubSkillImporter()
        headers = importer._get_headers()

        assert "Accept" in headers
        assert "X-GitHub-Api-Version" in headers
        assert "Authorization" not in headers

    def test_headers_with_token(self):
        """Test headers with authentication token."""
        importer = GitHubSkillImporter(github_token="test-token")
        headers = importer._get_headers()

        assert "Accept" in headers
        assert "X-GitHub-Api-Version" in headers
        assert headers["Authorization"] == "Bearer test-token"


class TestCheckResponse:
    """Tests for _check_response method."""

    def test_check_response_success(self):
        """Test successful response check."""
        importer = GitHubSkillImporter()
        response = MagicMock()
        response.status_code = 200

        # Should not raise
        importer._check_response(response)

    def test_check_response_rate_limit(self):
        """Test rate limit response."""
        importer = GitHubSkillImporter()
        response = MagicMock()
        response.status_code = 403
        response.headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "123"}
        response.text = "Rate limit"

        with pytest.raises(GitHubRateLimitError):
            importer._check_response(response)

    def test_check_response_forbidden_not_rate_limit(self):
        """Test forbidden response that's not rate limit."""
        importer = GitHubSkillImporter()
        response = MagicMock()
        response.status_code = 403
        response.headers = {"X-RateLimit-Remaining": "100"}
        response.text = "Access denied"

        with pytest.raises(GitHubSkillImporterError, match="Access forbidden"):
            importer._check_response(response)

    def test_check_response_not_found(self):
        """Test not found response."""
        importer = GitHubSkillImporter()
        response = MagicMock()
        response.status_code = 404
        response.text = "Not found"

        with pytest.raises(GitHubNotFoundError):
            importer._check_response(response)

    def test_check_response_unauthorized(self):
        """Test unauthorized response."""
        importer = GitHubSkillImporter()
        response = MagicMock()
        response.status_code = 401
        response.text = "Bad credentials"

        with pytest.raises(GitHubSkillImporterError, match="Authentication failed"):
            importer._check_response(response)

    def test_check_response_server_error(self):
        """Test server error response."""
        importer = GitHubSkillImporter()
        response = MagicMock()
        response.status_code = 500
        response.text = "Internal server error"

        with pytest.raises(GitHubSkillImporterError, match="GitHub API error: 500"):
            importer._check_response(response)


class TestGitHubRepoInfo:
    """Tests for GitHubRepoInfo dataclass."""

    def test_repo_info_basic(self):
        """Test basic GitHubRepoInfo creation."""
        info = GitHubRepoInfo(owner="owner", repo="repo")

        assert info.owner == "owner"
        assert info.repo == "repo"
        assert info.branch is None
        assert info.path is None

    def test_repo_info_full(self):
        """Test GitHubRepoInfo with all fields."""
        info = GitHubRepoInfo(
            owner="owner",
            repo="repo",
            branch="develop",
            path="skills/my-skill",
        )

        assert info.owner == "owner"
        assert info.repo == "repo"
        assert info.branch == "develop"
        assert info.path == "skills/my-skill"


class TestImportStaysOnPublicAddresses:
    @pytest.mark.asyncio
    async def test_a_zipball_redirect_to_the_metadata_address_is_not_followed(self, monkeypatch):
        from agentarea_common.utils.url_safety import OutboundPolicy, SafeOutboundTransport

        hosts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hosts.append(request.headers["host"])
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

        async def resolve(host: str, port: int) -> list[str]:
            return {"api.github.com": ["140.82.121.6"]}[host]

        def client(**kwargs):
            transport = SafeOutboundTransport(
                OutboundPolicy(), resolve=resolve, inner=lambda: httpx.MockTransport(handler)
            )
            return httpx.AsyncClient(transport=transport, **kwargs)

        monkeypatch.setattr(
            "agentarea_agents.infrastructure.github_skill_importer.safe_async_client", client
        )
        importer = GitHubSkillImporter(github_token="t0k")  # noqa: S106

        with pytest.raises(GitHubSkillImporterError):
            await importer.download_repo("https://github.com/owner/repo/tree/main")
        assert hosts == ["api.github.com"]

    @pytest.mark.asyncio
    async def test_an_archive_redirect_is_not_followed(self):
        hosts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hosts.append(request.url.host)
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

        importer = GitHubSkillImporter(transport=httpx.MockTransport(handler))

        with pytest.raises(GitHubSkillImporterError):
            await importer.download_repo("https://github.com/owner/repo/tree/main")
        assert hosts == ["codeload.github.com"]

    @pytest.mark.asyncio
    async def test_a_skill_file_fetch_refuses_a_non_public_address(self):
        from agentarea_agents.tools.skills_toolset import _fetch_text
        from agentarea_common.utils.url_safety import UnsafeUrlError

        with pytest.raises(UnsafeUrlError):
            await _fetch_text("http://127.0.0.1:8000/SKILL.md")
