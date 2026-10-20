"""A GitHub repository as a skill registry (ADR-0044).

The platform builds the index itself: every folder holding a SKILL.md at the
repository's head commit is one skill, named and described by its frontmatter,
and pointing at the folder's tree so install can fetch exactly that content. An
unchanged head is not read again. A private repository is read with the token
its credentials reference resolves to at sync time.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_registry.application.github_index import (
    GitHubIndexTooLargeError,
    GitHubTreeTruncatedError,
    build_github_skill_index,
)
from agentarea_registry.application.service import SYNC_FORMAT, RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)

COMMIT = "c" * 40
ROOT_TREE = "r" * 40


def _skill_md(name: str, description: str) -> bytes:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n".encode()


class StubGitHub:
    """The GitHub reads a sync makes, over an in-memory repository."""

    def __init__(self, files: dict[str, bytes], *, truncated: bool = False):
        self.commit = COMMIT
        self.files = files
        self.truncated = truncated
        self.calls: list[tuple] = []

    async def head(self, repo: str, ref: str | None) -> str:
        self.calls.append(("head", repo, ref))
        return self.commit

    async def tree(self, repo: str, commit: str) -> tuple[list[dict], str, bool]:
        self.calls.append(("tree", repo, commit))
        entries: list[dict] = []
        dirs: set[str] = set()
        for path in self.files:
            entries.append({"path": path, "type": "blob", "sha": f"blob:{path}"})
            parts = path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        entries.extend({"path": d, "type": "tree", "sha": f"tree:{d}"} for d in sorted(dirs))
        return entries, ROOT_TREE, self.truncated

    async def raw(self, repo: str, commit: str, path: str) -> bytes:
        self.calls.append(("raw", repo, commit, path))
        return self.files[path]


REPO_FILES = {
    "README.md": b"# skills",
    "skills/pdf/SKILL.md": _skill_md("pdf", "Read and fill PDF forms"),
    "skills/pdf/scripts/fill.py": b"print()",
    "skills/xlsx/SKILL.md": _skill_md("xlsx", "Spreadsheets"),
    "other/notes/SKILL.md": _skill_md("notes", "Outside the path"),
}


async def test_every_folder_with_a_skill_md_is_one_item():
    github = StubGitHub(REPO_FILES)

    items = await build_github_skill_index(
        github, repo="acme/skills", commit=COMMIT, path=None
    )

    by_id = {i["external_id"]: i for i in items}
    assert set(by_id) == {"skills/pdf", "skills/xlsx", "other/notes"}
    pdf = by_id["skills/pdf"]
    assert pdf["name"] == "pdf"
    assert pdf["description"] == "Read and fill PDF forms"
    assert pdf["spec"]["source"] == {
        "type": "github",
        "repo": "acme/skills",
        "path": "skills/pdf",
        "ref": COMMIT,
        "tree_sha": "tree:skills/pdf",
    }
    # The folder's tree is the content's identity: a new tree is a new version.
    assert pdf["version"] == "tree:skills/pdf"


async def test_path_limits_the_index_to_one_folder():
    items = await build_github_skill_index(
        StubGitHub(REPO_FILES), repo="acme/skills", commit=COMMIT, path="/skills/"
    )

    assert sorted(i["external_id"] for i in items) == ["skills/pdf", "skills/xlsx"]


async def test_a_skill_at_the_repository_root_points_at_the_root_tree():
    items = await build_github_skill_index(
        StubGitHub({"SKILL.md": _skill_md("solo", "One skill")}),
        repo="acme/solo",
        commit=COMMIT,
        path=None,
    )

    (item,) = items
    assert item["spec"]["source"]["path"] == ""
    assert item["spec"]["source"]["tree_sha"] == ROOT_TREE
    assert item["name"] == "solo"


async def test_a_skill_md_without_a_name_takes_its_folder_name():
    items = await build_github_skill_index(
        StubGitHub({"tools/lint/SKILL.md": b"# no frontmatter\n"}),
        repo="acme/skills",
        commit=COMMIT,
        path=None,
    )

    assert [(i["name"], i["description"]) for i in items] == [("lint", None)]


async def test_a_truncated_tree_fails_instead_of_dropping_skills():
    with pytest.raises(GitHubTreeTruncatedError):
        await build_github_skill_index(
            StubGitHub(REPO_FILES, truncated=True),
            repo="acme/skills",
            commit=COMMIT,
            path=None,
        )


@pytest_asyncio.fixture
async def registry(db_session):
    record = Registry(
        name="acme-skills",
        registry_type="skills",
        source_type="github",
        source_url="acme/skills",
        source_ref="main",
        scope="workspace",
        workspace_id="ws-acme",
        mode="upstream",
        trust="private",
    )
    db_session.add(record)
    await db_session.commit()
    return record


def _service(db_session, github: StubGitHub, tokens: list, resolver=None) -> RegistryService:
    def factory(token):
        tokens.append(token)
        return github

    return RegistryService(
        RegistryRepository(db_session),
        RegistryItemRepository(db_session),
        server_repo=None,
        github_source_factory=factory,
        credentials_resolver=resolver,
    )


async def test_sync_writes_the_items_and_skips_an_unchanged_head(db_session, registry):
    github = StubGitHub(REPO_FILES)
    service = _service(db_session, github, tokens=[])

    first = await service.sync_registry(registry.id)
    second = await service.sync_registry(registry.id)

    assert first["new_specs"] == 3
    assert second["source_unchanged"] is True
    assert [c[0] for c in github.calls].count("tree") == 1
    items = await RegistryItemRepository(db_session).list_by_registry(registry.id)
    assert {i.registry_workspace_id for i in items} == {"ws-acme"}
    assert {i.registry_trust for i in items} == {"private"}
    assert github.calls[0] == ("head", "acme/skills", "main")
    # The head is kept where an index URL keeps its ETag, with the same format prefix.
    await db_session.refresh(registry)
    assert registry.source_etag == f"{SYNC_FORMAT}:{COMMIT}"


async def test_a_new_head_is_read_again(db_session, registry):
    github = StubGitHub(REPO_FILES)
    service = _service(db_session, github, tokens=[])
    await service.sync_registry(registry.id)

    github.commit = "d" * 40
    github.files = {**REPO_FILES, "skills/docx/SKILL.md": _skill_md("docx", "Documents")}
    stats = await service.sync_registry(registry.id)

    assert (stats["total"], stats["new_specs"]) == (4, 1)


async def test_a_private_repository_is_read_with_the_resolved_token(db_session, registry):
    seen: list = []

    async def resolve(reg):
        seen.append(reg.id)
        return "ghp_secret"

    await RegistryRepository(db_session).update(registry.id, credentials_secret_ref=uuid4())
    tokens: list = []
    await _service(db_session, StubGitHub(REPO_FILES), tokens, resolver=resolve).sync_registry(
        registry.id
    )

    assert tokens == ["ghp_secret"]
    assert seen == [registry.id]
    # The token is used, never kept.
    reloaded = await RegistryRepository(db_session).get_by_id(registry.id)
    assert "ghp_secret" not in repr(vars(reloaded))


async def test_credentials_without_a_resolver_fail_the_sync(db_session, registry):
    await RegistryRepository(db_session).update(registry.id, credentials_secret_ref=uuid4())

    with pytest.raises(ValueError, match="credentials"):
        await _service(db_session, StubGitHub(REPO_FILES), tokens=[]).sync_registry(registry.id)


async def test_a_public_repository_is_read_without_a_token(db_session, registry):
    tokens: list = []
    await _service(db_session, StubGitHub(REPO_FILES), tokens).sync_registry(registry.id)

    assert tokens == [None]


async def test_skill_bodies_are_read_raw_not_through_the_rate_limited_api():
    # 60 API calls an hour per egress IP, shared by every tenant: the index
    # spends two (head and tree), however many skills the repository holds.
    github = StubGitHub(REPO_FILES)

    await build_github_skill_index(
        github, repo="acme/skills", commit=COMMIT, path=None
    )

    assert [c[0] for c in github.calls] == ["tree", "raw", "raw", "raw"]
    assert ("raw", "acme/skills", COMMIT, "skills/pdf/SKILL.md") in github.calls


async def test_a_repository_with_more_skills_than_the_cap_is_refused():
    with pytest.raises(GitHubIndexTooLargeError, match="more than 2 skills"):
        await build_github_skill_index(
            StubGitHub(REPO_FILES),
            repo="acme/skills",
            commit=COMMIT,
            path=None,
            max_skills=2,
        )


def _bomb_frontmatter(kind: str) -> bytes:
    if kind == "merge":
        levels = ["a0: &a0 {x: 1}"] + [
            f"a{i}: &a{i} {{<<: [*a{i - 1}, *a{i - 1}]}}" for i in range(1, 28)
        ]
    else:
        levels = ['a0: &a0 ["x", "x"]'] + [
            f"a{i}: &a{i} [*a{i - 1}, *a{i - 1}]" for i in range(1, 40)
        ]
    return ("---\nname: bomb\n" + "\n".join(levels) + "\n---\n# Bomb\n").encode()


@pytest.mark.parametrize("kind", ["merge", "alias"])
async def test_a_frontmatter_bomb_is_refused_at_once(kind):
    # A ~750-byte merge-key bomb in one SKILL.md took minutes and gigabytes
    # through yaml.safe_load; the folder now takes its folder name.
    import time

    started = time.monotonic()

    items = await build_github_skill_index(
        StubGitHub({"tools/bomb/SKILL.md": _bomb_frontmatter(kind)}),
        repo="acme/skills",
        commit=COMMIT,
        path=None,
    )

    assert time.monotonic() - started < 1
    assert [i["name"] for i in items] == ["bomb"]


async def test_frontmatters_are_parsed_off_the_event_loop():
    import asyncio

    big = "\n".join(f"k{i}: {'v' * 40}" for i in range(600))
    files = {
        f"skills/s{n}/SKILL.md": f"---\nname: s{n}\n{big}\n---\n# S\n".encode() for n in range(12)
    }
    gaps: list[float] = []
    stop = asyncio.Event()

    async def ticker() -> None:
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            started = loop.time()
            await asyncio.sleep(0.01)
            gaps.append(loop.time() - started)

    ticking = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    loop = asyncio.get_running_loop()
    started = loop.time()
    items = await build_github_skill_index(
        StubGitHub(files), repo="acme/skills", commit=COMMIT, path=None
    )
    elapsed = loop.time() - started
    stop.set()
    await ticking

    assert len(items) == 12
    assert len(gaps) >= 5
    assert max(gaps) < elapsed / 2
