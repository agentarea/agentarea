"""GitHub skill importer for downloading skill packages from GitHub repositories."""

import io
import logging
import posixpath
import re
import zipfile
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from agentarea_common.utils.url_safety import safe_async_client

logger = logging.getLogger(__name__)

MAX_GITHUB_REPO_ZIP_BYTES = 25 * 1024 * 1024
MAX_GITHUB_PACKAGE_FILES = 200
MAX_GITHUB_PACKAGE_BYTES = 10 * 1024 * 1024


@dataclass
class GitHubRepoInfo:
    """Parsed GitHub repository information."""

    owner: str
    repo: str
    branch: str | None = None
    path: str | None = None  # Subdirectory path if specified


class GitHubSkillImporterError(Exception):
    """Base exception for GitHub skill importer errors."""

    pass


class GitHubRateLimitError(GitHubSkillImporterError):
    """Raised when GitHub API rate limit is exceeded."""

    pass


class GitHubNotFoundError(GitHubSkillImporterError):
    """Raised when repository is not found or is private."""

    pass


class GitHubInvalidURLError(GitHubSkillImporterError):
    """Raised when the GitHub URL is invalid."""

    pass


def extract_skill_package(repo_zip_data: bytes, *, package_path: str | None) -> bytes:
    """Re-root one skill package from a GitHub repository zipball.

    ``package_path`` is the package directory inside the repository, or the
    path of its SKILL.md; empty means the repository root.
    """
    if len(repo_zip_data) > MAX_GITHUB_REPO_ZIP_BYTES:
        mb = MAX_GITHUB_REPO_ZIP_BYTES // (1024 * 1024)
        raise ValueError(f"GitHub repository ZIP exceeds {mb} MB limit")

    package_path = (package_path or "").strip("/")
    if posixpath.basename(package_path).lower() == "skill.md":
        package_path = posixpath.dirname(package_path)
    package_prefix = f"{package_path}/" if package_path else ""

    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(repo_zip_data)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        selected: list[tuple[zipfile.ZipInfo, str]] = []
        total_size = 0
        for info in source.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/", 1)
            if len(parts) != 2:
                continue
            relative = parts[1]
            if package_prefix:
                if not relative.startswith(package_prefix):
                    continue
                relative = relative[len(package_prefix) :]
            if not relative or relative.startswith("__MACOSX/"):
                continue
            selected.append((info, relative))
            total_size += info.file_size
            if len(selected) > MAX_GITHUB_PACKAGE_FILES:
                raise ValueError(
                    f"GitHub skill package contains more than {MAX_GITHUB_PACKAGE_FILES} files"
                )
            if total_size > MAX_GITHUB_PACKAGE_BYTES:
                mb = MAX_GITHUB_PACKAGE_BYTES // (1024 * 1024)
                raise ValueError(f"GitHub skill package exceeds {mb} MB uncompressed limit")

        if not selected:
            raise ValueError(f"No files found at '{package_path or '/'}' in the GitHub repository")

        for info, relative in selected:
            target.writestr(relative, source.read(info.filename))

    return out.getvalue()


class GitHubSkillImporter:
    """Service for downloading skill packages from GitHub repositories.

    Supports various GitHub URL formats:
    - https://github.com/owner/repo
    - https://github.com/owner/repo/tree/branch
    - https://github.com/owner/repo/tree/branch/path
    - git@github.com:owner/repo.git
    """

    GITHUB_API_BASE = "https://api.github.com"
    DEFAULT_TIMEOUT = 30.0

    def __init__(self, github_token: str | None = None):
        """Initialize the importer.

        Args:
            github_token: Optional GitHub personal access token for higher rate limits
                         and access to private repositories.
        """
        self.github_token = github_token

    def parse_github_url(self, url: str) -> GitHubRepoInfo:
        """Parse a GitHub URL to extract repository information.

        Args:
            url: GitHub URL in various formats.

        Returns:
            GitHubRepoInfo with owner, repo, branch, and path.

        Raises:
            GitHubInvalidURLError: If the URL cannot be parsed.
        """
        url = url.strip()

        # Handle git@ SSH URLs
        ssh_match = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
        if ssh_match:
            return GitHubRepoInfo(
                owner=ssh_match.group(1),
                repo=ssh_match.group(2),
            )

        # Handle HTTPS URLs
        try:
            parsed = urlparse(url)
        except Exception as e:
            raise GitHubInvalidURLError(f"Invalid URL: {url}") from e

        if parsed.netloc not in ("github.com", "www.github.com"):
            raise GitHubInvalidURLError(f"Not a GitHub URL: {url}")

        # Parse path: /owner/repo[/tree/branch[/path...]]
        path_parts = parsed.path.strip("/").split("/")

        if len(path_parts) < 2:
            raise GitHubInvalidURLError(f"Invalid GitHub repository URL: {url}")

        owner = path_parts[0]
        repo = path_parts[1]

        # Remove .git suffix if present
        if repo.endswith(".git"):
            repo = repo[:-4]

        branch = None
        subpath = None

        # Check for /tree/branch/path or /blob/branch/path
        if len(path_parts) >= 4 and path_parts[2] in ("tree", "blob"):
            branch = path_parts[3]
            if len(path_parts) > 4:
                subpath = "/".join(path_parts[4:])

        return GitHubRepoInfo(
            owner=owner,
            repo=repo,
            branch=branch,
            path=subpath,
        )

    async def download_repo(self, github_url: str) -> bytes:
        """Download a repository as a ZIP file.

        Args:
            github_url: GitHub repository URL.

        Returns:
            ZIP file content as bytes.

        Raises:
            GitHubRateLimitError: If rate limit is exceeded.
            GitHubNotFoundError: If repository is not found.
            GitHubSkillImporterError: For other errors.
        """
        repo_info = self.parse_github_url(github_url)

        # Determine the branch/ref to download
        ref = repo_info.branch or await self._get_default_branch(repo_info.owner, repo_info.repo)

        # Build the zipball URL
        zipball_url = (
            f"{self.GITHUB_API_BASE}/repos/{repo_info.owner}/{repo_info.repo}/zipball/{ref}"
        )

        logger.info(f"Downloading repository from {zipball_url}")

        headers = self._get_headers()

        async with safe_async_client(timeout=self.DEFAULT_TIMEOUT, follow_redirects=True) as client:
            try:
                response = await client.get(zipball_url, headers=headers)
                self._check_response(response)
                return response.content

            except httpx.TimeoutException as e:
                raise GitHubSkillImporterError(f"Timeout downloading repository: {e}") from e
            except httpx.RequestError as e:
                raise GitHubSkillImporterError(f"Error downloading repository: {e}") from e

    async def get_repo_info(self, github_url: str) -> dict:
        """Get repository information from GitHub API.

        Args:
            github_url: GitHub repository URL.

        Returns:
            Repository information dict from GitHub API.
        """
        repo_info = self.parse_github_url(github_url)
        api_url = f"{self.GITHUB_API_BASE}/repos/{repo_info.owner}/{repo_info.repo}"

        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            response = await client.get(api_url, headers=headers)
            self._check_response(response)
            return response.json()

    async def _get_default_branch(self, owner: str, repo: str) -> str:
        """Get the default branch for a repository.

        Args:
            owner: Repository owner.
            repo: Repository name.

        Returns:
            Default branch name (e.g., 'main' or 'master').
        """
        api_url = f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}"
        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            response = await client.get(api_url, headers=headers)
            self._check_response(response)
            data = response.json()
            return data.get("default_branch", "main")

    def _get_headers(self) -> dict[str, str]:
        """Get headers for GitHub API requests."""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        return headers

    def _check_response(self, response: httpx.Response) -> None:
        """Check response for errors and raise appropriate exceptions.

        Args:
            response: HTTP response to check.

        Raises:
            GitHubRateLimitError: If rate limit is exceeded.
            GitHubNotFoundError: If resource is not found.
            GitHubSkillImporterError: For other HTTP errors.
        """
        if response.status_code == 200:
            return

        if response.status_code == 403:
            # Check if it's rate limiting
            remaining = response.headers.get("X-RateLimit-Remaining", "0")
            if remaining == "0":
                reset_time = response.headers.get("X-RateLimit-Reset", "unknown")
                raise GitHubRateLimitError(
                    f"GitHub API rate limit exceeded. Resets at {reset_time}. "
                    "Consider providing a GitHub token for higher limits."
                )
            raise GitHubSkillImporterError(f"Access forbidden: {response.text}")

        if response.status_code == 404:
            raise GitHubNotFoundError(
                "Repository not found. It may be private or the URL may be incorrect."
            )

        if response.status_code == 401:
            raise GitHubSkillImporterError("Authentication failed. Check your GitHub token.")

        raise GitHubSkillImporterError(
            f"GitHub API error: {response.status_code} - {response.text}"
        )
