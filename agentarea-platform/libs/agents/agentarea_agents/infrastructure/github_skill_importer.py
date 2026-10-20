"""GitHub skill importer for downloading skill packages from GitHub repositories."""

import asyncio
import hashlib
import io
import logging
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from agentarea_common import github_git
from agentarea_common.outbound import Destination, outbound_client
from agentarea_common.utils.url_safety import safe_async_client

logger = logging.getLogger(__name__)

MAX_GITHUB_REPO_ZIP_BYTES = 25 * 1024 * 1024
MAX_GITHUB_PACKAGE_FILES = 200
MAX_GITHUB_PACKAGE_BYTES = 10 * 1024 * 1024
FOLDER_DOWNLOAD_CONCURRENCY = 8

_REPO_PART = re.compile(r"[A-Za-z0-9_.-]+")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")


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


class GitHubTreeMismatchError(GitHubSkillImporterError):
    """The folder at the pinned commit is not the tree the catalog names."""


class GitHubSourceGoneError(GitHubNotFoundError):
    """The repository or folder a catalog skill points at is not there any more."""


@dataclass(frozen=True)
class GitHubFolder:
    """One folder of a repository at one commit, its files verified by blob SHA."""

    commit: str
    tree_sha: str
    files: dict[str, bytes]


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data, usedforsecurity=False).hexdigest()


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

    RAW_BASE = "https://raw.githubusercontent.com"
    CODELOAD_BASE = github_git.CODELOAD

    def __init__(
        self,
        github_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        """Initialize the importer.

        Args:
            github_token: Optional GitHub personal access token for higher rate limits
                         and access to private repositories.
            transport: HTTP transport for ``download_folder`` (tests pass a mock).
        """
        self.github_token = github_token
        self._transport = transport
        # A commit's tree never changes: every folder of one commit (a mirror
        # sync of a repository) costs one API call, not one per folder.
        self._commit_trees: dict[str, Any] = {}

    async def download_folder(
        self, repo: str, path: str, *, ref: str | None, tree_sha: str | None
    ) -> GitHubFolder:
        """Download one folder of ``repo`` at a commit, as the catalog pins it.

        ``ref`` names the commit; a branch or tag is resolved to its head, and
        none means the default branch's head, which is then the pin. With
        ``tree_sha`` the folder at that commit must be exactly that tree, else
        nothing is returned. What is returned is the content the tree names.
        Links, submodules and hidden files are left out, as a ZIP upload leaves
        hidden files out.

        Without a token nothing goes through the REST API, whose anonymous
        budget (60 requests an hour) the whole deployment shares: the ref is
        resolved over git smart HTTP, the files come from the commit's archive,
        and the folder's tree SHA is computed from them. With a token the API
        is asked once for a pinned commit (the recursive tree of the commit),
        once more to resolve a missing ref, and once more when the repository
        is too large to list whole; files come from raw.githubusercontent.com,
        each checked against its blob SHA.

        Raises:
            GitHubSourceGoneError: The repository or the folder is not there
                any more.
            GitHubTreeMismatchError: The folder is not the pinned tree.
        """
        parts = repo.split("/")
        if len(parts) != 2 or not all(
            _REPO_PART.fullmatch(p) and p not in (".", "..") for p in parts
        ):
            raise GitHubSkillImporterError(f"Not a GitHub repository name: {repo!r}")
        owner, name = parts
        folder = path.strip("/")
        where = f"{repo}/{folder}" if folder else repo
        if not self.github_token:
            return await self._download_folder_from_archive(repo, folder, where, ref, tree_sha)
        api = f"{self.GITHUB_API_BASE}/repos/{owner}/{name}"

        async with outbound_client(
            Destination.VENDOR,
            timeout=self.DEFAULT_TIMEOUT,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            try:
                commit = await self._resolve_commit(client, api, ref)
                tree_url = f"{api}/git/trees/{commit}?recursive=1"
                tree = self._commit_trees.get(tree_url)
                if tree is None:
                    tree = self._commit_trees[tree_url] = await self._api_json(client, tree_url)
            except GitHubNotFoundError as e:
                raise GitHubSourceGoneError(
                    f"The skill was removed upstream: {repo} is not on GitHub any more"
                ) from e
            entries = [e for e in tree.get("tree") or [] if isinstance(e, dict)]
            if folder:
                resolved_tree = next(
                    (
                        e.get("sha")
                        for e in entries
                        if e.get("path") == folder and e.get("type") == "tree"
                    ),
                    None,
                )
                if not resolved_tree:
                    if tree.get("truncated"):
                        raise GitHubSkillImporterError(f"{repo} is too large to list")
                    raise GitHubSourceGoneError(
                        f"The skill was removed upstream: {where} is not in {repo} at {commit}"
                    )
                prefix = f"{folder}/"
                entries = [
                    {**e, "path": e["path"][len(prefix) :]}
                    for e in entries
                    if str(e.get("path", "")).startswith(prefix)
                ]
            else:
                resolved_tree = tree.get("sha")
            if tree_sha and resolved_tree != tree_sha:
                raise GitHubTreeMismatchError(
                    f"{where} at {commit} is tree {resolved_tree}, "
                    f"not {tree_sha} as the catalog pins it"
                )
            if tree.get("truncated"):
                subtree = await self._api_json(
                    client, f"{api}/git/trees/{resolved_tree}?recursive=1"
                )
                if subtree.get("truncated"):
                    raise GitHubSkillImporterError(f"{where} is too large to list")
                entries = [e for e in subtree.get("tree") or [] if isinstance(e, dict)]
            blobs = self._package_blobs(entries, where)
            base = f"{self.RAW_BASE}/{owner}/{name}/{commit}/"
            if folder:
                base += quote(folder) + "/"
            limit = asyncio.Semaphore(FOLDER_DOWNLOAD_CONCURRENCY)

            async def fetch(rel: str, sha: str) -> tuple[str, bytes]:
                async with limit:
                    try:
                        response = await client.get(base + quote(rel), headers=self._raw_headers())
                    except httpx.RequestError as e:
                        raise GitHubSkillImporterError(
                            f"Error reading {rel} of {where}: {e}"
                        ) from e
                if response.status_code == 404:
                    raise GitHubSourceGoneError(
                        f"The skill was removed upstream: {rel} of {where} is gone"
                    )
                self._check_response(response)
                if git_blob_sha(response.content) != sha:
                    raise GitHubSkillImporterError(
                        f"{rel} of {where} at {commit} does not match its blob SHA"
                    )
                return rel, response.content

            files = dict(await asyncio.gather(*(fetch(rel, sha) for rel, sha in blobs)))
        return GitHubFolder(commit=commit, tree_sha=str(resolved_tree), files=files)

    async def _download_folder_from_archive(
        self, repo: str, folder: str, where: str, ref: str | None, tree_sha: str | None
    ) -> GitHubFolder:
        def packaged(rel: str, mode: str) -> bool:
            return mode != github_git.SYMLINK_MODE and not any(
                p.startswith(".") for p in rel.split("/")
            )

        try:
            commit = await github_git.resolve_commit(repo, ref, transport=self._transport)
            entries = await github_git.read_archive(
                repo,
                commit,
                prefix=folder,
                keep=packaged,
                max_kept_files=MAX_GITHUB_PACKAGE_FILES,
                max_kept_bytes=MAX_GITHUB_PACKAGE_BYTES,
                transport=self._transport,
            )
        except github_git.GitHubGitRateLimitError as e:
            raise GitHubRateLimitError(str(e)) from e
        except github_git.GitHubGitNotFoundError as e:
            raise GitHubSourceGoneError(
                f"The skill was removed upstream: {repo} is not on GitHub any more ({e})"
            ) from e
        except github_git.GitHubArchiveTooLargeError as e:
            raise ValueError(
                f"GitHub skill package exceeds its limits ({MAX_GITHUB_PACKAGE_FILES} files, "
                f"{MAX_GITHUB_PACKAGE_BYTES // (1024 * 1024)} MB): {e}"
            ) from e
        except github_git.GitHubGitError as e:
            raise GitHubSkillImporterError(str(e)) from e
        if not entries:
            raise GitHubSourceGoneError(
                f"The skill was removed upstream: {where} is not in {repo} at {commit}"
            )
        resolved_tree = github_git.git_tree_shas(
            {rel: (entry.mode, entry.sha) for rel, entry in entries.items()}
        )[""]
        if tree_sha and resolved_tree != tree_sha:
            raise GitHubTreeMismatchError(
                f"{where} at {commit} is tree {resolved_tree}, "
                f"not {tree_sha} as the catalog pins it"
            )
        files = {rel: entry.data for rel, entry in entries.items() if entry.data is not None}
        for rel in entries.keys() - files.keys():
            logger.info("Leaving %s out of the skill package from %s", rel, where)
        if not files:
            raise ValueError(f"No files found in {where}")
        return GitHubFolder(commit=commit, tree_sha=resolved_tree, files=files)

    async def _resolve_commit(self, client: httpx.AsyncClient, api: str, ref: str | None) -> str:
        if ref and _GIT_SHA.fullmatch(ref):
            return ref
        target = quote(ref, safe="") if ref else "HEAD"
        sha = (await self._api_json(client, f"{api}/commits/{target}")).get("sha")
        if not isinstance(sha, str) or not _GIT_SHA.fullmatch(sha):
            raise GitHubSkillImporterError(f"{api} did not resolve {ref or 'HEAD'!r} to a commit")
        return sha

    @staticmethod
    def _package_blobs(entries: list[Any], where: str) -> list[tuple[str, str]]:
        blobs: list[tuple[str, str]] = []
        total = 0
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") not in ("blob", "commit"):
                continue
            rel = str(entry.get("path") or "")
            if (
                entry.get("type") == "commit"
                or entry.get("mode") == "120000"
                or any(p.startswith(".") for p in rel.split("/"))
            ):
                logger.info("Leaving %s out of the skill package from %s", rel, where)
                continue
            blobs.append((rel, str(entry.get("sha"))))
            total += int(entry.get("size") or 0)
            if len(blobs) > MAX_GITHUB_PACKAGE_FILES:
                raise ValueError(
                    f"GitHub skill package contains more than {MAX_GITHUB_PACKAGE_FILES} files"
                )
            if total > MAX_GITHUB_PACKAGE_BYTES:
                mb = MAX_GITHUB_PACKAGE_BYTES // (1024 * 1024)
                raise ValueError(f"GitHub skill package exceeds {mb} MB uncompressed limit")
        if not blobs:
            raise ValueError(f"No files found in {where}")
        return blobs

    async def _api_json(self, client: httpx.AsyncClient, url: str) -> Any:
        try:
            response = await client.get(url, headers=self._get_headers())
        except httpx.TimeoutException as e:
            raise GitHubSkillImporterError(f"Timeout reading {url}: {e}") from e
        except httpx.RequestError as e:
            raise GitHubSkillImporterError(f"Error reading {url}: {e}") from e
        self._check_response(response)
        return response.json()

    def _raw_headers(self) -> dict[str, str]:
        if self.github_token:
            return {"Authorization": f"Bearer {self.github_token}"}
        return {}

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
        if not self.github_token:
            return await self._download_repo_archive(repo_info)

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
                return await self._bounded_download(client, zipball_url, headers)
            except httpx.TimeoutException as e:
                raise GitHubSkillImporterError(f"Timeout downloading repository: {e}") from e
            except httpx.RequestError as e:
                raise GitHubSkillImporterError(f"Error downloading repository: {e}") from e

    async def _download_repo_archive(self, repo_info: GitHubRepoInfo) -> bytes:
        """The repository's ZIP from its archive endpoint: no REST call, no token."""
        if not all(
            _REPO_PART.fullmatch(p) and p not in (".", "..")
            for p in (repo_info.owner, repo_info.repo)
        ):
            raise GitHubInvalidURLError(
                f"Not a GitHub repository: {repo_info.owner}/{repo_info.repo}"
            )
        ref = quote(repo_info.branch or "HEAD", safe="")
        url = f"{self.CODELOAD_BASE}/{repo_info.owner}/{repo_info.repo}/zip/{ref}"
        logger.info("Downloading repository from %s", url)
        # The host is fixed and answers directly: a redirect is not followed.
        async with outbound_client(
            Destination.VENDOR, timeout=self.DEFAULT_TIMEOUT, transport=self._transport
        ) as client:
            try:
                return await self._bounded_download(client, url, {})
            except httpx.TimeoutException as e:
                raise GitHubSkillImporterError(f"Timeout downloading repository: {e}") from e
            except httpx.RequestError as e:
                raise GitHubSkillImporterError(f"Error downloading repository: {e}") from e

    async def _bounded_download(
        self, client: httpx.AsyncClient, url: str, headers: dict[str, str]
    ) -> bytes:
        """The body at ``url``, refused as soon as it passes the repository ZIP cap."""
        body = bytearray()
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code != 200:
                await response.aread()
                self._check_response(response)
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_GITHUB_REPO_ZIP_BYTES:
                    mb = MAX_GITHUB_REPO_ZIP_BYTES // (1024 * 1024)
                    raise ValueError(f"GitHub repository ZIP exceeds {mb} MB limit")
        return bytes(body)

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

        async with outbound_client(Destination.VENDOR, timeout=self.DEFAULT_TIMEOUT) as client:
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

        async with outbound_client(Destination.VENDOR, timeout=self.DEFAULT_TIMEOUT) as client:
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

        if response.status_code == 429:
            raise GitHubRateLimitError("GitHub throttled the request; retry later.")

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
