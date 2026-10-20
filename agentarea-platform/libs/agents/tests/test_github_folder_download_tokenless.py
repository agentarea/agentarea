"""Without a token, a skill folder is read without GitHub's REST API (ADR-0044).

The ref resolves over git smart HTTP and the files come from the commit's
archive, so an install from a public repository never spends the 60 requests an
hour a deployment's anonymous REST calls share. The folder's tree SHA is
computed from the files, so a pointer that names one is still verified and one
that does not is pinned to it.
"""

import io
import tarfile

import httpx
import pytest
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubRateLimitError,
    GitHubSkillImporter,
    GitHubSourceGoneError,
    GitHubTreeMismatchError,
)
from agentarea_common import github_git
from agentarea_common.github_git import git_blob_sha, git_tree_shas

COMMIT = "1" * 40
FILES = {
    "skills/pdf/SKILL.md": ("100644", b"---\nname: pdf\n---\n# PDF"),
    "skills/pdf/scripts/fill.py": ("100755", b"print(1)"),
    "skills/pdf/.github/x.yml": ("100644", b"hidden"),
    "skills/pdf/link": ("120000", b"SKILL.md"),
    "README.md": ("100644", b"# repo"),
}
PDF_TREE = git_tree_shas(
    {p[len("skills/pdf/") :]: (m, git_blob_sha(d)) for p, (m, d) in FILES.items() if "pdf/" in p}
)[""]


@pytest.fixture(autouse=True)
def _fresh_archives():
    github_git.clear_archive_cache()
    yield
    github_git.clear_archive_cache()


def tarball(files=FILES) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        root = tarfile.TarInfo(f"repo-{COMMIT}")
        root.type = tarfile.DIRTYPE
        tar.addfile(root)
        for path, (mode, data) in sorted(files.items()):
            info = tarfile.TarInfo(f"repo-{COMMIT}/{path}")
            if mode == "120000":
                info.type, info.linkname = tarfile.SYMTYPE, data.decode()
                tar.addfile(info)
                continue
            info.size, info.mode = len(data), 0o775 if mode == "100755" else 0o664
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def ls_refs(sha: str) -> bytes:
    line = f"{sha} HEAD symref-target:refs/heads/main\n".encode()
    return b"%04x" % (len(line) + 4) + line + b"0000"


class FakeGitHub:
    def __init__(self, files=FILES):
        self.archive = tarball(files)
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.method} {request.url}")
        if request.url.host == "api.github.com":
            raise AssertionError(f"REST API called without a token: {request.url}")
        if str(request.url) == "https://github.com/owner/repo.git/git-upload-pack":
            return httpx.Response(200, content=ls_refs(COMMIT))
        if str(request.url) == f"https://codeload.github.com/owner/repo/tar.gz/{COMMIT}":
            return httpx.Response(200, content=self.archive)
        if request.url.host == "github.com":
            return httpx.Response(401)
        return httpx.Response(404)


def importer(github) -> GitHubSkillImporter:
    return GitHubSkillImporter(transport=httpx.MockTransport(github))


async def test_a_pointer_without_ref_is_resolved_and_pinned_by_its_computed_tree():
    github = FakeGitHub()

    folder = await importer(github).download_folder(
        "owner/repo", "skills/pdf", ref=None, tree_sha=None
    )

    assert folder.commit == COMMIT
    assert folder.tree_sha == PDF_TREE
    assert folder.files == {"SKILL.md": b"---\nname: pdf\n---\n# PDF", "scripts/fill.py": b"print(1)"}
    assert github.requests == [
        "POST https://github.com/owner/repo.git/git-upload-pack",
        f"GET https://codeload.github.com/owner/repo/tar.gz/{COMMIT}",
    ]


async def test_a_pinned_commit_needs_only_its_archive():
    github = FakeGitHub()

    folder = await importer(github).download_folder(
        "owner/repo", "skills/pdf", ref=COMMIT, tree_sha=PDF_TREE
    )

    assert folder.tree_sha == PDF_TREE
    assert github.requests == [f"GET https://codeload.github.com/owner/repo/tar.gz/{COMMIT}"]


async def test_a_folder_that_is_not_the_pinned_tree_is_refused():
    with pytest.raises(GitHubTreeMismatchError, match=PDF_TREE):
        await importer(FakeGitHub()).download_folder(
            "owner/repo", "skills/pdf", ref=COMMIT, tree_sha="9" * 40
        )


async def test_a_folder_gone_from_the_commit_is_removed_upstream():
    with pytest.raises(GitHubSourceGoneError, match="removed"):
        await importer(FakeGitHub()).download_folder(
            "owner/repo", "skills/absent", ref=COMMIT, tree_sha=None
        )


async def test_a_repository_gone_from_github_is_removed_upstream():
    with pytest.raises(GitHubSourceGoneError, match="removed"):
        await importer(FakeGitHub()).download_folder(
            "owner/gone", "skills/pdf", ref=None, tree_sha=None
        )


async def test_throttling_is_reported_as_a_rate_limit():
    throttled = GitHubSkillImporter(
        transport=httpx.MockTransport(lambda _r: httpx.Response(429))
    )

    with pytest.raises(GitHubRateLimitError):
        await throttled.download_folder("owner/repo", "skills/pdf", ref=None, tree_sha=None)


async def test_a_folder_over_the_package_caps_is_refused():
    many = {f"skills/pdf/f{i}.md": ("100644", b"x") for i in range(201)}

    with pytest.raises(ValueError, match="200"):
        await importer(FakeGitHub({**FILES, **many})).download_folder(
            "owner/repo", "skills/pdf", ref=COMMIT, tree_sha=None
        )


async def test_one_commit_is_downloaded_once_for_every_folder_of_it():
    github = FakeGitHub()
    reader = importer(github)

    await reader.download_folder("owner/repo", "skills/pdf", ref=COMMIT, tree_sha=None)
    await reader.download_folder("owner/repo", "skills/pdf", ref=COMMIT, tree_sha=None)

    assert len(github.requests) == 1


async def test_a_repository_import_downloads_the_archive_without_the_rest_api():
    github = FakeGitHub()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "codeload.github.com":
            github.requests.append(str(request.url))
            return httpx.Response(200, content=b"PK zip")
        return github(request)

    data = await GitHubSkillImporter(transport=httpx.MockTransport(handler)).download_repo(
        "https://github.com/owner/repo/tree/develop/skills/pdf"
    )

    assert data == b"PK zip"
    assert github.requests == ["https://codeload.github.com/owner/repo/zip/develop"]
