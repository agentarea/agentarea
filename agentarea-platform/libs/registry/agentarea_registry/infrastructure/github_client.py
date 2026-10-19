"""GitHub REST reads a skill registry sync makes."""

from typing import Any
from urllib.parse import quote

import httpx
from agentarea_common.utils.outbound_tls import outbound_ssl_context

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"
TIMEOUT_SECONDS = 30.0
# The index reads a SKILL.md for its frontmatter only.
RAW_READ_BYTES = 64 * 1024


class GitHubApiError(RuntimeError):
    """GitHub refused or failed a read."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class HttpGitHubSource:
    """Reads one repository's commits, trees and blobs, with a token for private ones."""

    def __init__(self, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "agentarea-registry-sync",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def _get(self, path: str, **params: Any) -> Any:
        async with httpx.AsyncClient(
            base_url=GITHUB_API,
            timeout=TIMEOUT_SECONDS,
            verify=outbound_ssl_context(),
            transport=self._transport,
        ) as client:
            response = await client.get(path, headers=self._headers, params=params)
        if response.status_code != 200:
            raise GitHubApiError(
                f"GitHub {path} answered {response.status_code}: {response.text[:200]}",
                response.status_code,
            )
        return response.json()

    async def head(self, repo: str, ref: str | None) -> tuple[str, str]:
        branch: str = ref or (await self._get(f"/repos/{repo}"))["default_branch"]
        commit = await self._get(f"/repos/{repo}/commits/{quote(branch, safe='')}")
        return commit["sha"], commit["commit"]["tree"]["sha"]

    async def tree(self, repo: str, tree_sha: str) -> tuple[list[dict[str, Any]], bool]:
        data = await self._get(f"/repos/{repo}/git/trees/{tree_sha}", recursive="1")
        return list(data.get("tree", [])), bool(data.get("truncated"))

    async def raw(self, repo: str, commit: str, path: str) -> bytes:
        headers = {"User-Agent": self._headers["User-Agent"]}
        if "Authorization" in self._headers:
            headers["Authorization"] = self._headers["Authorization"]
        url = f"{GITHUB_RAW}/{repo}/{commit}/{quote(path)}"
        body = bytearray()
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, verify=outbound_ssl_context(), transport=self._transport
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
