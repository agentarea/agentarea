"""GitHub content read without the REST API: refs over smart HTTP, files from the archive."""

import io
import tarfile

import httpx
import pytest
from agentarea_common import github_git
from agentarea_common.github_git import (
    GitHubArchiveTooLargeError,
    GitHubGitError,
    GitHubGitNotFoundError,
    GitHubGitRateLimitError,
    git_blob_sha,
    git_tree_shas,
    read_archive,
    resolve_commit,
)

COMMIT = "a" * 40
TAG_OBJECT = "b" * 40
TAG_COMMIT = "c" * 40

# Built with git itself: `git rev-parse HEAD: HEAD:pdf HEAD:pdf/scripts` over these files.
REPO_FILES = {
    "README.md": ("100644", b"# r"),
    "pdf/SKILL.md": ("100644", b"---\nname: pdf\n---\n# PDF\n"),
    "pdf/scripts/fill.py": ("100755", b"print(1)\n"),
    "pdf/scripts.txt": ("100644", b"x"),
    "pdf/scripts-x": ("100644", b"y"),
    "pdf/.hidden": ("100644", b"h"),
    "pdf/link": ("120000", b"SKILL.md"),
}
ROOT_TREE = "7a7d867bfe09514968eb597cf3f739fe65759d97"  # pragma: allowlist secret
PDF_TREE = "c2a66e687339a9b1ebc9ba58c76b2d265c6c0c7c"  # pragma: allowlist secret
SCRIPTS_TREE = "5139e05fcdd3b495e2687faf38d5471bb4a401fe"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _fresh_cache():
    github_git.clear_archive_cache()
    yield
    github_git.clear_archive_cache()


def archive(files=REPO_FILES, root=f"repo-{COMMIT}") -> bytes:
    """A tarball shaped like the one GitHub's archive endpoint serves."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        dirs = {root}
        for path in files:
            parts = path.split("/")[:-1]
            dirs.update(f"{root}/" + "/".join(parts[: i + 1]) for i in range(len(parts)))
        for d in sorted(dirs):
            info = tarfile.TarInfo(d)
            info.type = tarfile.DIRTYPE
            info.mode = 0o775
            tar.addfile(info)
        for path, (mode, data) in sorted(files.items()):
            info = tarfile.TarInfo(f"{root}/{path}")
            if mode == "120000":
                info.type = tarfile.SYMTYPE
                info.linkname = data.decode()
                tar.addfile(info)
                continue
            info.size = len(data)
            info.mode = 0o775 if mode == "100755" else 0o664
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def pkt(line: str) -> bytes:
    data = line.encode()
    return b"%04x" % (len(data) + 4) + data


def ls_refs_answer(*lines: str) -> bytes:
    return b"".join(pkt(f"{line}\n") for line in lines) + b"0000"


class FakeGitHub:
    def __init__(self, *, refs: bytes | None = None, tarball: bytes | None = None):
        self.refs = refs if refs is not None else ls_refs_answer(
            f"{COMMIT} HEAD symref-target:refs/heads/main",
            f"{COMMIT} refs/heads/main",
        )
        self.tarball = tarball if tarball is not None else archive()
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "github.com" and request.url.path == "/owner/repo.git/git-upload-pack":
            return httpx.Response(200, content=self.refs)
        if request.url.host == "codeload.github.com" and request.url.path == (
            f"/owner/repo/tar.gz/{COMMIT}"
        ):
            return httpx.Response(200, content=self.tarball)
        if request.url.host == "github.com":
            return httpx.Response(401)
        return httpx.Response(404)


def transport(github: FakeGitHub) -> httpx.MockTransport:
    return httpx.MockTransport(github)


def test_tree_shas_are_the_ones_git_computes():
    shas = git_tree_shas({p: (mode, git_blob_sha(data)) for p, (mode, data) in REPO_FILES.items()})

    assert shas[""] == ROOT_TREE
    assert shas["pdf"] == PDF_TREE
    assert shas["pdf/scripts"] == SCRIPTS_TREE


async def test_head_is_resolved_with_one_ls_refs_request_and_no_rest_call():
    github = FakeGitHub()

    commit = await resolve_commit("owner/repo", None, transport=transport(github))

    assert commit == COMMIT
    [request] = github.requests
    assert request.method == "POST"
    assert request.headers["Git-Protocol"] == "version=2"
    assert b"command=ls-refs" in request.content
    assert b"ref-prefix HEAD" in request.content


async def test_a_branch_resolves_to_its_head():
    github = FakeGitHub()

    assert await resolve_commit("owner/repo", "main", transport=transport(github)) == COMMIT
    assert b"ref-prefix refs/heads/main" in github.requests[0].content


async def test_an_annotated_tag_resolves_to_the_commit_it_points_at():
    github = FakeGitHub(refs=ls_refs_answer(f"{TAG_OBJECT} refs/tags/v1 peeled:{TAG_COMMIT}"))

    assert await resolve_commit("owner/repo", "v1", transport=transport(github)) == TAG_COMMIT


async def test_a_commit_sha_needs_no_request():
    github = FakeGitHub()

    assert await resolve_commit("owner/repo", COMMIT, transport=transport(github)) == COMMIT
    assert github.requests == []


async def test_a_ref_the_repository_does_not_have_is_an_error():
    github = FakeGitHub(refs=ls_refs_answer())

    with pytest.raises(GitHubGitError, match="nope"):
        await resolve_commit("owner/repo", "nope", transport=transport(github))


async def test_a_missing_or_private_repository_is_not_found():
    with pytest.raises(GitHubGitNotFoundError):
        await resolve_commit("owner/gone", None, transport=transport(FakeGitHub()))


async def test_github_throttling_is_a_rate_limit():
    limited = httpx.MockTransport(lambda _r: httpx.Response(429))

    with pytest.raises(GitHubGitRateLimitError):
        await resolve_commit("owner/repo", None, transport=limited)
    with pytest.raises(GitHubGitRateLimitError):
        await read_archive("owner/repo", COMMIT, prefix="", transport=limited)


@pytest.mark.parametrize("repo", ["owner", "owner/repo/x", "../x", "owner/.."])
async def test_a_malformed_repository_name_is_refused(repo):
    with pytest.raises(GitHubGitError):
        await resolve_commit(repo, None, transport=transport(FakeGitHub()))


async def test_a_folder_is_read_from_the_archive_with_every_file_hashed():
    github = FakeGitHub()

    files = await read_archive(
        "owner/repo",
        COMMIT,
        prefix="pdf",
        keep=lambda path, mode: not path.startswith(".") and mode != "120000",
        transport=transport(github),
    )

    assert set(files) == {"SKILL.md", "scripts/fill.py", "scripts.txt", "scripts-x", ".hidden", "link"}
    assert files["scripts/fill.py"].mode == "100755"
    assert files["scripts/fill.py"].data == b"print(1)\n"
    assert files[".hidden"].data is None
    assert files["link"].mode == "120000"
    assert files["link"].data is None
    assert git_tree_shas({p: (f.mode, f.sha) for p, f in files.items()})[""] == PDF_TREE
    assert [r.url.host for r in github.requests] == ["codeload.github.com"]


async def test_one_commit_is_downloaded_once_for_every_folder_of_it():
    github = FakeGitHub()

    await read_archive("owner/repo", COMMIT, prefix="pdf", transport=transport(github))
    whole = await read_archive("owner/repo", COMMIT, prefix="", transport=transport(github))

    assert "README.md" in whole
    assert len(github.requests) == 1


async def test_an_archive_over_its_byte_cap_is_refused():
    github = FakeGitHub()

    with pytest.raises(GitHubArchiveTooLargeError):
        await read_archive(
            "owner/repo", COMMIT, prefix="", transport=transport(github), max_archive_bytes=64
        )


async def test_kept_content_over_its_cap_is_refused():
    big = {"pdf/SKILL.md": ("100644", b"x" * 4096), "pdf/b.md": ("100644", b"y" * 4096)}
    github = FakeGitHub(tarball=archive(big))

    with pytest.raises(GitHubArchiveTooLargeError):
        await read_archive(
            "owner/repo", COMMIT, prefix="pdf", transport=transport(github), max_kept_bytes=6000
        )
    with pytest.raises(GitHubArchiveTooLargeError):
        await read_archive(
            "owner/repo", COMMIT, prefix="pdf", transport=transport(github), max_kept_files=1
        )


async def test_an_archive_that_is_not_there_is_not_found():
    with pytest.raises(GitHubGitNotFoundError):
        await read_archive("owner/repo", "d" * 40, prefix="", transport=transport(FakeGitHub()))


async def test_what_is_unpacked_outside_the_prefix_counts_against_the_cap(monkeypatch):
    # Skipping a member of a gzip stream still inflates it: a small archive of
    # zeros beside the folder must not make a worker inflate gigabytes.
    monkeypatch.setattr(github_git, "MAX_ARCHIVE_UNPACKED_BYTES", 10_000)
    big = {"pdf/SKILL.md": ("100644", b"# s"), "other/zeros.bin": ("100644", b"\0" * 20_000)}
    github = FakeGitHub(tarball=archive(big))

    with pytest.raises(GitHubArchiveTooLargeError, match="unpacks"):
        await read_archive("owner/repo", COMMIT, prefix="pdf", transport=transport(github))
