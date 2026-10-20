"""The GitHub reads a skill registry sync makes.

A registry with credentials reads through the REST API with its token. One
without reads nothing through the REST API, whose 60 anonymous requests an hour
every tenant of a deployment shares: the head resolves over git smart HTTP and
the listing, the tree SHAs and the SKILL.md files come from the commit's archive
(``agentarea_common.github_git``).
"""

import posixpath
from collections import OrderedDict
from typing import Any
from urllib.parse import quote

import httpx
from agentarea_common import github_git
from agentarea_common.outbound import Destination, outbound_client

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"
TIMEOUT_SECONDS = 30.0
# The index reads a SKILL.md for its frontmatter only.
RAW_READ_BYTES = 64 * 1024
SKILL_FILE = "SKILL.md"
# SKILL.md bodies an archive listing keeps, at most RAW_READ_BYTES each read.
MAX_ARCHIVE_SKILL_BYTES = 64 * 1024 * 1024
# A folder's tree at a commit never changes: (repo, commit, path) -> tree SHA.
FOLDER_TREE_CACHE_ENTRIES = 4096
_folder_trees: OrderedDict[tuple[str, str, str], str] = OrderedDict()


class GitHubApiError(RuntimeError):
    """GitHub refused or failed a read."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class HttpGitHubSource:
    """Reads one repository's commits, trees and blobs through the REST API, with a token."""

    def __init__(self, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "agentarea-registry-sync",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._root_trees: dict[str, str] = {}

    async def _get(self, path: str, **params: Any) -> Any:
        async with outbound_client(
            Destination.VENDOR,
            base_url=GITHUB_API,
            timeout=TIMEOUT_SECONDS,
            transport=self._transport,
        ) as client:
            response = await client.get(path, headers=self._headers, params=params)
        if response.status_code != 200:
            raise GitHubApiError(
                f"GitHub {path} answered {response.status_code}: {response.text[:200]}",
                response.status_code,
            )
        return response.json()

    async def head(self, repo: str, ref: str | None) -> str:
        commit = await self._get(f"/repos/{repo}/commits/{quote(ref or 'HEAD', safe='')}")
        self._root_trees[commit["sha"]] = commit["commit"]["tree"]["sha"]
        return commit["sha"]

    async def tree(self, repo: str, commit: str) -> tuple[list[dict[str, Any]], str, bool]:
        data = await self._get(
            f"/repos/{repo}/git/trees/{self._root_trees.get(commit, commit)}", recursive="1"
        )
        return list(data.get("tree", [])), str(data.get("sha")), bool(data.get("truncated"))

    async def raw(self, repo: str, commit: str, path: str) -> bytes:
        headers = {"User-Agent": self._headers["User-Agent"]}
        if "Authorization" in self._headers:
            headers["Authorization"] = self._headers["Authorization"]
        url = f"{GITHUB_RAW}/{repo}/{commit}/{quote(path)}"
        body = bytearray()
        async with outbound_client(
            Destination.VENDOR, timeout=TIMEOUT_SECONDS, transport=self._transport
        ) as c:
            async with c.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    raise GitHubApiError(
                        f"GitHub raw {repo}/{path} answered {response.status_code}",
                        response.status_code,
                    )
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) >= RAW_READ_BYTES:
                        break
        return bytes(body[:RAW_READ_BYTES])


class ArchiveGitHubSource:
    """Reads a public repository without the REST API: refs over git, files from its archive."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._files: dict[tuple[str, str], dict[str, github_git.GitFile]] = {}

    async def head(self, repo: str, ref: str | None) -> str:
        try:
            return await github_git.resolve_commit(repo, ref, transport=self._transport)
        except github_git.GitHubGitError as e:
            raise _api_error(e) from e

    async def _snapshot(self, repo: str, commit: str) -> dict[str, github_git.GitFile]:
        if (repo, commit) not in self._files:
            try:
                self._files[(repo, commit)] = await github_git.read_archive(
                    repo,
                    commit,
                    prefix="",
                    keep=lambda path, mode: (
                        posixpath.basename(path) == SKILL_FILE and mode != github_git.SYMLINK_MODE
                    ),
                    max_kept_bytes=MAX_ARCHIVE_SKILL_BYTES,
                    transport=self._transport,
                )
            except github_git.GitHubGitError as e:
                raise _api_error(e) from e
        return self._files[(repo, commit)]

    async def tree(self, repo: str, commit: str) -> tuple[list[dict[str, Any]], str, bool]:
        files = await self._snapshot(repo, commit)
        trees = github_git.git_tree_shas({p: (f.mode, f.sha) for p, f in files.items()})
        entries: list[dict[str, Any]] = [
            {"path": path, "type": "blob", "mode": f.mode, "sha": f.sha}
            for path, f in files.items()
        ]
        entries.extend({"path": p, "type": "tree", "sha": sha} for p, sha in trees.items() if p)
        return entries, trees[""], False

    async def raw(self, repo: str, commit: str, path: str) -> bytes:
        entry = (await self._snapshot(repo, commit)).get(path)
        if entry is None or entry.data is None:
            raise GitHubApiError(f"{repo}/{path} is not in the archive of {commit}", 404)
        return entry.data[:RAW_READ_BYTES]


def _api_error(error: github_git.GitHubGitError) -> GitHubApiError:
    if isinstance(error, github_git.GitHubGitNotFoundError):
        return GitHubApiError(str(error), 404)
    if isinstance(error, github_git.GitHubGitRateLimitError):
        return GitHubApiError(str(error), 429)
    return GitHubApiError(str(error))


def github_source(token: str | None) -> HttpGitHubSource | ArchiveGitHubSource:
    """The REST API with a registry's token, or the token-free archive without one."""
    return HttpGitHubSource(token) if token else ArchiveGitHubSource()


async def folder_tree_sha(
    source: dict[str, Any], *, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """The tree SHA a GitHub pointer's folder is now, read token-free.

    One git ref read when the pointer names a branch (or none); the commit's
    archive only the first time a folder is asked about at that commit.
    """
    repo, path = str(source["repo"]), str(source.get("path") or "").strip("/")
    commit = await github_git.resolve_commit(repo, source.get("ref"), transport=transport)
    key = (repo, commit, path)
    cached = _folder_trees.get(key)
    if cached is not None:
        _folder_trees.move_to_end(key)
        return cached
    files = await github_git.read_archive(
        repo, commit, prefix=path, keep=lambda _path, _mode: False, transport=transport
    )
    if not files:
        raise GitHubApiError(f"{repo}/{path} is not in {repo} at {commit}", 404)
    tree = github_git.git_tree_shas({p: (f.mode, f.sha) for p, f in files.items()})[""]
    _folder_trees[key] = tree
    while len(_folder_trees) > FOLDER_TREE_CACHE_ENTRIES:
        _folder_trees.popitem(last=False)
    return tree
