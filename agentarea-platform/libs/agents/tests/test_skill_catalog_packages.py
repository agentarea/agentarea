"""Catalog skill packages are stored once, under the digest of their files (ADR-0044)."""

import pytest
from agentarea_agents.infrastructure.skill_storage_service import (
    is_catalog_package,
    package_digest,
)

from .fake_s3 import fake_storage


def test_the_digest_is_independent_of_the_order_files_are_given_in():
    files = {"SKILL.md": b"# A", "scripts/run.sh": b"echo", "README.md": b"r"}

    assert package_digest(files) == package_digest(dict(reversed(list(files.items()))))


@pytest.mark.parametrize(
    "other",
    [
        {"SKILL.md": b"# B"},
        {"skill.md": b"# A"},
        {"SKILL.md": b"# A", "extra": b""},
    ],
)
def test_the_digest_changes_with_any_path_or_byte(other):
    assert package_digest({"SKILL.md": b"# A"}) != package_digest(other)


def test_the_digest_does_not_confuse_where_a_path_ends_and_its_bytes_begin():
    assert package_digest({"ab": b"c"}) != package_digest({"a": b"bc"})


async def test_a_package_is_stored_under_its_digest_once():
    storage, s3 = fake_storage()
    files = {"SKILL.md": b"# Skill", "scripts/run.sh": b"echo hi"}

    first = await storage.store_catalog_package(files)
    puts_after_first = len(s3.puts)
    second = await storage.store_catalog_package(dict(reversed(list(files.items()))))

    assert first == second == f"skills/catalog/{package_digest(files)}/"
    assert is_catalog_package(first)
    assert s3.under(first) == files
    assert len(s3.puts) == puts_after_first == 2


async def test_a_partly_stored_package_is_completed_not_trusted():
    storage, s3 = fake_storage()
    files = {"SKILL.md": b"# Skill", "notes.md": b"n"}
    prefix = f"skills/catalog/{package_digest(files)}/"
    s3.objects[f"{prefix}SKILL.md"] = b"# Skill"

    assert await storage.store_catalog_package(files) == prefix
    assert s3.puts == [f"{prefix}notes.md"]


@pytest.mark.parametrize("path", ["../escape.md", "a/../../b", "/etc/passwd/..", ""])
async def test_a_package_with_an_unsafe_path_is_refused_whole(path):
    storage, s3 = fake_storage()

    with pytest.raises(ValueError):
        await storage.store_catalog_package({"SKILL.md": b"# S", path: b"x"})
    assert s3.objects == {}


async def test_an_over_budget_package_is_refused_whole(monkeypatch):
    from agentarea_agents.infrastructure import skill_storage_service

    monkeypatch.setattr(skill_storage_service, "MAX_PACKAGE_FILES", 1)
    storage, s3 = fake_storage()

    with pytest.raises(ValueError, match="more than 1 files"):
        await storage.store_catalog_package({"SKILL.md": b"# S", "b": b"b"})
    assert s3.objects == {}


async def test_read_package_returns_every_file():
    storage, _ = fake_storage()
    files = {"SKILL.md": b"# Skill", "a/b.txt": b"\x00\x01"}
    prefix = await storage.store_catalog_package(files)

    assert await storage.read_package(prefix) == files


async def test_a_github_tree_alias_points_at_the_stored_package():
    storage, _ = fake_storage()
    prefix = await storage.store_catalog_package({"SKILL.md": b"# S"})

    assert await storage.get_github_tree_package("c" * 40) is None
    await storage.put_github_tree_package("c" * 40, prefix)
    assert await storage.get_github_tree_package("c" * 40) == prefix


def test_only_the_digest_area_is_a_catalog_package():
    assert is_catalog_package(f"skills/catalog/{'a' * 64}/")
    assert not is_catalog_package("skills/ws-1/skill-1/")
    assert not is_catalog_package(None)
