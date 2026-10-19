"""A repository index reads SKILL.md files raw, outside GitHub's rate-limited API."""

import httpx
import pytest
from agentarea_registry.infrastructure.github_client import (
    RAW_READ_BYTES,
    GitHubApiError,
    HttpGitHubSource,
)

COMMIT = "c" * 40


async def test_a_file_is_read_raw_at_the_commit_with_the_token():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"---\nname: pdf\n---\n" + b"x" * (2 * RAW_READ_BYTES))

    source = HttpGitHubSource("ghp_token", transport=httpx.MockTransport(handler))

    body = await source.raw("acme/skills", COMMIT, "skills/my pdf/SKILL.md")

    assert len(body) == RAW_READ_BYTES
    assert str(seen[0].url) == (
        f"https://raw.githubusercontent.com/acme/skills/{COMMIT}/skills/my%20pdf/SKILL.md"
    )
    assert seen[0].headers["Authorization"] == "Bearer ghp_token"


async def test_a_missing_file_is_a_github_error():
    source = HttpGitHubSource(transport=httpx.MockTransport(lambda _r: httpx.Response(404)))

    with pytest.raises(GitHubApiError) as error:
        await source.raw("acme/skills", COMMIT, "SKILL.md")
    assert error.value.status_code == 404
