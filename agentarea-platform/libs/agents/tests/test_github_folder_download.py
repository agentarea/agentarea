"""Downloading one skill folder through the REST API, as a configured token does."""

import hashlib
import json

import httpx
import pytest
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubSkillImporter,
    GitHubSkillImporterError,
    GitHubSourceGoneError,
    GitHubTreeMismatchError,
)

COMMIT = "1" * 40
TREE = "2" * 40
OTHER_TREE = "3" * 40


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data, usedforsecurity=False).hexdigest()


FILES = {"SKILL.md": b"---\nname: pdf\n---\n# PDF", "scripts/fill.py": b"print(1)"}


class FakeGitHub:
    """Routes the GitHub API and raw-content requests the importer makes."""

    def __init__(self, *, folder_tree=TREE, files=FILES, extra_entries=(), truncated=False):
        self.folder_tree = folder_tree
        self.files = dict(files)
        self.extra_entries = list(extra_entries)
        self.truncated = truncated
        self.raw_overrides: dict[str, bytes] = {}
        self.requests: list[str] = []

    @property
    def api_calls(self) -> list[str]:
        return [r for r in self.requests if "api.github.com" in r]

    def _entries(self, prefix: str) -> list[dict]:
        entries = [
            {"path": f"{prefix}{rel}", "mode": "100644", "type": "blob", "sha": blob_sha(data)}
            for rel, data in self.files.items()
        ]
        entries.append({"path": f"{prefix}scripts", "mode": "040000", "type": "tree", "sha": "t"})
        entries.extend({**e, "path": f"{prefix}{e['path']}"} for e in self.extra_entries)
        return entries

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.requests.append(str(url))
        path = url.path
        if url.host == "raw.githubusercontent.com":
            prefix = f"/owner/repo/{COMMIT}/skills/pdf/"
            rel = path[len(prefix) :]
            if not path.startswith(prefix) or rel not in self.files:
                return httpx.Response(404)
            return httpx.Response(200, content=self.raw_overrides.get(rel, self.files[rel]))
        if path == "/repos/owner/repo/commits/HEAD":
            return httpx.Response(200, json={"sha": COMMIT})
        if path == f"/repos/owner/repo/git/trees/{COMMIT}":
            assert url.params["recursive"] == "1"
            root = [
                {"path": "skills", "mode": "040000", "type": "tree", "sha": "s"},
                {"path": "skills/pdf", "mode": "040000", "type": "tree", "sha": self.folder_tree},
                {"path": "README.md", "mode": "100644", "type": "blob", "sha": "r"},
            ]
            entries = root if self.truncated else root + self._entries("skills/pdf/")
            body = {"sha": "0" * 40, "tree": entries, "truncated": self.truncated}
            return httpx.Response(200, content=json.dumps(body))
        if path == f"/repos/owner/repo/git/trees/{self.folder_tree}":
            body = {"sha": self.folder_tree, "tree": self._entries(""), "truncated": False}
            return httpx.Response(200, content=json.dumps(body))
        return httpx.Response(404, json={"message": "Not Found"})


def importer(github: FakeGitHub) -> GitHubSkillImporter:
    return GitHubSkillImporter(github_token="t0k", transport=httpx.MockTransport(github))  # noqa: S106


async def test_one_api_call_lists_the_pinned_folder_and_raw_serves_its_files():
    github = FakeGitHub()

    folder = await importer(github).download_folder(
        "owner/repo", "skills/pdf", ref=COMMIT, tree_sha=TREE
    )

    assert folder.commit == COMMIT
    assert folder.tree_sha == TREE
    assert folder.files == FILES
    assert github.api_calls == [
        f"https://api.github.com/repos/owner/repo/git/trees/{COMMIT}?recursive=1"
    ]
    assert not any("/contents" in r for r in github.requests)


async def test_a_folder_whose_tree_moved_on_is_refused():
    github = FakeGitHub(folder_tree=OTHER_TREE)

    with pytest.raises(GitHubTreeMismatchError, match=TREE):
        await importer(github).download_folder(
            "owner/repo", "skills/pdf", ref=COMMIT, tree_sha=TREE
        )
    assert not any("raw.githubusercontent.com" in r for r in github.requests)


async def test_without_a_ref_the_default_branch_head_is_resolved_and_pinned():
    github = FakeGitHub()

    folder = await importer(github).download_folder(
        "owner/repo", "skills/pdf", ref=None, tree_sha=None
    )

    assert folder.commit == COMMIT
    assert folder.tree_sha == TREE
    assert folder.files == FILES
    assert len(github.api_calls) == 2


async def test_a_file_that_does_not_match_its_blob_sha_is_refused():
    github = FakeGitHub()
    github.raw_overrides["SKILL.md"] = b"# tampered"

    with pytest.raises(GitHubSkillImporterError, match=r"SKILL\.md"):
        await importer(github).download_folder(
            "owner/repo", "skills/pdf", ref=COMMIT, tree_sha=TREE
        )


async def test_a_truncated_repository_listing_lists_the_folder_by_its_tree():
    github = FakeGitHub(truncated=True)

    folder = await importer(github).download_folder(
        "owner/repo", "skills/pdf", ref=COMMIT, tree_sha=TREE
    )

    assert folder.files == FILES
    assert github.api_calls[-1] == (
        f"https://api.github.com/repos/owner/repo/git/trees/{TREE}?recursive=1"
    )


async def test_links_submodules_and_hidden_files_are_left_out():
    github = FakeGitHub(
        extra_entries=[
            {"path": "link", "mode": "120000", "type": "blob", "sha": "l"},
            {"path": "vendor", "mode": "160000", "type": "commit", "sha": "c"},
            {"path": ".github/workflow.yml", "mode": "100644", "type": "blob", "sha": "h"},
        ]
    )

    folder = await importer(github).download_folder(
        "owner/repo", "skills/pdf", ref=COMMIT, tree_sha=TREE
    )

    assert folder.files == FILES


async def test_a_folder_gone_from_its_repository_is_reported_as_removed_upstream():
    with pytest.raises(GitHubSourceGoneError, match="removed"):
        await importer(FakeGitHub()).download_folder(
            "owner/repo", "skills/absent", ref=COMMIT, tree_sha=None
        )


async def test_a_repository_gone_from_github_is_reported_as_removed_upstream():
    with pytest.raises(GitHubSourceGoneError, match="removed"):
        await importer(FakeGitHub()).download_folder(
            "owner/gone", "skills/pdf", ref=COMMIT, tree_sha=None
        )


async def test_a_repository_root_skill_is_the_commit_tree():
    with pytest.raises(GitHubTreeMismatchError, match="0" * 40):
        await importer(FakeGitHub()).download_folder(
            "owner/repo", "", ref=COMMIT, tree_sha=OTHER_TREE
        )


async def test_a_configured_token_is_sent_to_the_api_and_to_raw():
    seen: list[str | None] = []
    github = FakeGitHub()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization"))
        return github(request)

    await GitHubSkillImporter(
        github_token="t0k",  # noqa: S106
        transport=httpx.MockTransport(handler),
    ).download_folder("owner/repo", "skills/pdf", ref=COMMIT, tree_sha=TREE)

    assert seen
    assert set(seen) == {"Bearer t0k"}


@pytest.mark.parametrize("repo", ["owner", "owner/repo/extra", "../x", "owner/.."])
async def test_a_malformed_repo_is_refused(repo):
    with pytest.raises(GitHubSkillImporterError):
        await importer(FakeGitHub()).download_folder(repo, "skills/pdf", ref=COMMIT, tree_sha=None)


async def test_one_importer_reads_a_commits_tree_once_for_every_folder_of_it():
    github = FakeGitHub()
    pdf = importer(github)

    await pdf.download_folder("owner/repo", "skills/pdf", ref=COMMIT, tree_sha=TREE)
    await pdf.download_folder("owner/repo", "skills/pdf", ref=COMMIT, tree_sha=TREE)

    assert github.api_calls == [
        f"https://api.github.com/repos/owner/repo/git/trees/{COMMIT}?recursive=1"
    ]
