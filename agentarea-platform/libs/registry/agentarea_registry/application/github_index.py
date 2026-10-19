"""The index of a GitHub repository whose folders are skills (ADR-0044).

Every folder holding a ``SKILL.md`` at one commit is one skill. Its item points
at that folder's tree, the pointer shape the platform skill index uses
(``spec.source``), so an install fetches exactly the content the index named.
"""

import logging
import posixpath
import re
from typing import Any, Protocol

import yaml

logger = logging.getLogger(__name__)

SKILL_FILE = "SKILL.md"
GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)


def is_github_repo(value: str) -> bool:
    """``owner/repo`` exactly: no trailing newline, no ``.`` or ``..`` for a name."""
    return bool(GITHUB_REPO_PATTERN.fullmatch(value)) and value.split("/")[1] not in {".", ".."}


class GitHubIndexTooLargeError(ValueError):
    """The repository holds more skill folders than this registry may index."""


class GitHubTreeTruncatedError(ValueError):
    """GitHub returned part of the tree; an index built from it would drop skills."""


class GitHubSource(Protocol):
    async def head(self, repo: str, ref: str | None) -> tuple[str, str]:
        """``(commit sha, root tree sha)`` of ``ref``, or of the default branch."""
        ...

    async def tree(self, repo: str, tree_sha: str) -> tuple[list[dict[str, Any]], bool]:
        """Every entry under ``tree_sha`` recursively, and whether GitHub truncated it."""
        ...

    async def raw(self, repo: str, commit: str, path: str) -> bytes:
        """The start of a file at ``commit``, read outside the rate-limited REST API."""
        ...


def skill_frontmatter(content: str) -> dict[str, Any]:
    match = _FRONTMATTER.match(content)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        logger.warning("Unreadable SKILL.md frontmatter", exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


async def build_github_skill_index(
    source: GitHubSource,
    *,
    repo: str,
    commit: str,
    root_tree: str,
    path: str | None,
    max_skills: int | None = None,
) -> list[dict[str, Any]]:
    """Catalog items for every skill folder of ``repo`` at ``commit`` under ``path``.

    ``max_skills`` refuses a repository with more folders than that, before any
    of them is read.
    """
    entries, truncated = await source.tree(repo, root_tree)
    if truncated:
        raise GitHubTreeTruncatedError(
            f"GitHub truncated the tree of {repo} at {commit}; set a path to a smaller folder"
        )
    prefix = (path or "").strip("/")
    trees = {e["path"]: e["sha"] for e in entries if e.get("type") == "tree"}
    skill_files = [
        entry
        for entry in sorted(entries, key=lambda e: e["path"])
        if entry.get("type") == "blob"
        and posixpath.basename(entry["path"]) == SKILL_FILE
        and (
            not prefix
            or posixpath.dirname(entry["path"]) == prefix
            or posixpath.dirname(entry["path"]).startswith(f"{prefix}/")
        )
    ]
    if max_skills is not None and len(skill_files) > max_skills:
        raise GitHubIndexTooLargeError(
            f"{repo} holds more than {max_skills} skills; set a path to a smaller folder"
        )
    items: list[dict[str, Any]] = []
    for entry in skill_files:
        folder = posixpath.dirname(entry["path"])
        tree_sha = trees[folder] if folder else root_tree
        meta = skill_frontmatter(
            (await source.raw(repo, commit, entry["path"])).decode("utf-8", "replace")
        )
        name = meta.get("name") if isinstance(meta.get("name"), str) and meta["name"] else None
        name = name or posixpath.basename(folder) or repo.rsplit("/", 1)[-1]
        description = meta.get("description")
        items.append(
            {
                "external_id": folder or name,
                "name": name,
                "description": description if isinstance(description, str) else None,
                "version": tree_sha,
                "spec": {
                    "source_type": "github",
                    "source_url": f"https://github.com/{repo}/tree/{commit}/{folder}".rstrip("/"),
                    "source": {
                        "type": "github",
                        "repo": repo,
                        "path": folder,
                        "ref": commit,
                        "tree_sha": tree_sha,
                    },
                },
                "tags": [],
            }
        )
    return items
