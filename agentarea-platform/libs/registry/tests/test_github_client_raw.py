"""The GitHub reads a repository index makes: REST with a token, git and archive without."""

import io
import tarfile

import httpx
import pytest
from agentarea_common import github_git
from agentarea_common.github_git import git_blob_sha, git_tree_shas
from agentarea_registry.application.github_index import build_github_skill_index
from agentarea_registry.infrastructure import github_client
from agentarea_registry.infrastructure.github_client import (
    RAW_READ_BYTES,
    ArchiveGitHubSource,
    GitHubApiError,
    HttpGitHubSource,
    PointerTrees,
    github_source,
)

COMMIT = "c" * 40


@pytest.fixture(autouse=True)
def _fresh_archives():
    github_git.clear_archive_cache()
    github_client.clear_commit_trees()
    yield
    github_git.clear_archive_cache()
    github_client.clear_commit_trees()


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


def test_only_a_registry_with_credentials_uses_the_rest_api():
    assert isinstance(github_source("ghp_token"), HttpGitHubSource)
    assert isinstance(github_source(None), ArchiveGitHubSource)


FILES = {
    "README.md": b"# skills",
    "skills/pdf/SKILL.md": b"---\nname: pdf\ndescription: PDFs\n---\n# PDF\n",
    "skills/pdf/scripts/fill.py": b"print()",
    "skills/xlsx/SKILL.md": b"---\nname: xlsx\n---\n# XLSX\n",
}


def _tarball() -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for path, data in sorted(FILES.items()):
            info = tarfile.TarInfo(f"skills-{COMMIT}/{path}")
            info.size, info.mode = len(data), 0o664
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


async def test_a_public_repository_is_indexed_with_one_ref_read_and_one_archive():
    requests: list[str] = []
    line = f"{COMMIT} refs/heads/main\n".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(f"{request.url.host}{request.url.path}")
        if request.url.host == "github.com":
            return httpx.Response(200, content=b"%04x" % (len(line) + 4) + line + b"0000")
        if request.url.host == "codeload.github.com":
            return httpx.Response(200, content=_tarball())
        raise AssertionError(f"unexpected request {request.url}")

    source = ArchiveGitHubSource(transport=httpx.MockTransport(handler))

    commit = await source.head("acme/skills", "main")
    items = await build_github_skill_index(source, repo="acme/skills", commit=commit, path=None)

    expected = git_tree_shas(
        {
            p[len("skills/pdf/") :]: ("100644", git_blob_sha(d))
            for p, d in FILES.items()
            if p.startswith("skills/pdf/")
        }
    )[""]
    by_id = {i["external_id"]: i for i in items}
    assert set(by_id) == {"skills/pdf", "skills/xlsx"}
    assert by_id["skills/pdf"]["description"] == "PDFs"
    assert by_id["skills/pdf"]["spec"]["source"]["tree_sha"] == expected
    assert by_id["skills/pdf"]["version"] == expected
    assert requests == [
        "github.com/acme/skills.git/git-upload-pack",
        f"codeload.github.com/acme/skills/tar.gz/{COMMIT}",
    ]


async def test_a_repository_the_archive_cannot_find_is_a_404():
    source = ArchiveGitHubSource(transport=httpx.MockTransport(lambda _r: httpx.Response(401)))

    with pytest.raises(GitHubApiError) as error:
        await source.head("acme/gone", None)
    assert error.value.status_code == 404


async def test_pointers_of_one_repository_cost_one_ref_read_and_one_unpack(monkeypatch):
    requests: list[str] = []
    unpacks: list[str] = []
    line = f"{COMMIT} refs/heads/main\n".encode()
    real_read = github_git.read_archive

    async def counting_read(repo, commit, **kwargs):
        unpacks.append(commit)
        return await real_read(repo, commit, **kwargs)

    monkeypatch.setattr(github_git, "read_archive", counting_read)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        if request.url.host == "github.com":
            return httpx.Response(200, content=b"%04x" % (len(line) + 4) + line + b"0000")
        return httpx.Response(200, content=_tarball())

    lookup = PointerTrees(transport=httpx.MockTransport(handler))
    pdf = await lookup({"type": "github", "repo": "acme/skills", "path": "skills/pdf", "ref": "main"})
    xlsx = await lookup({"type": "github", "repo": "acme/skills", "path": "skills/xlsx", "ref": "main"})

    expected = git_tree_shas(
        {
            p[len("skills/pdf/") :]: ("100644", git_blob_sha(d))
            for p, d in FILES.items()
            if p.startswith("skills/pdf/")
        }
    )[""]
    assert pdf == expected
    assert xlsx != pdf
    assert requests == ["github.com", "codeload.github.com"]
    assert unpacks == [COMMIT]
    with pytest.raises(GitHubApiError) as gone:
        await lookup({"type": "github", "repo": "acme/skills", "path": "absent", "ref": "main"})
    assert gone.value.status_code == 404
