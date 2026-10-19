"""GitHub REST reads a skill registry sync makes."""

import base64
from typing import Any
from urllib.parse import quote

import httpx
from agentarea_common.utils.outbound_tls import outbound_ssl_context

GITHUB_API = "https://api.github.com"
TIMEOUT_SECONDS = 30.0


class GitHubApiError(RuntimeError):
    """GitHub refused or failed a read."""


class HttpGitHubSource:
    """Reads one repository's commits, trees and blobs, with a token for private ones."""

    def __init__(self, token: str | None = None):
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "agentarea-registry-sync",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def _get(self, path: str, **params: Any) -> Any:
        async with httpx.AsyncClient(
            base_url=GITHUB_API, timeout=TIMEOUT_SECONDS, verify=outbound_ssl_context()
        ) as client:
            response = await client.get(path, headers=self._headers, params=params)
        if response.status_code != 200:
            raise GitHubApiError(
                f"GitHub {path} answered {response.status_code}: {response.text[:200]}"
            )
        return response.json()

    async def head(self, repo: str, ref: str | None) -> tuple[str, str]:
        branch: str = ref or (await self._get(f"/repos/{repo}"))["default_branch"]
        commit = await self._get(f"/repos/{repo}/commits/{quote(branch, safe='')}")
        return commit["sha"], commit["commit"]["tree"]["sha"]

    async def tree(self, repo: str, tree_sha: str) -> tuple[list[dict[str, Any]], bool]:
        data = await self._get(f"/repos/{repo}/git/trees/{tree_sha}", recursive="1")
        return list(data.get("tree", [])), bool(data.get("truncated"))

    async def blob(self, repo: str, sha: str) -> bytes:
        data = await self._get(f"/repos/{repo}/git/blobs/{sha}")
        if data.get("encoding") != "base64":
            raise GitHubApiError(f"GitHub blob {sha} of {repo} is not base64-encoded")
        return base64.b64decode(data["content"])
