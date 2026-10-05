"""Skill package paths become object-store keys next to other workspaces' skills,
and uploads are inflated in memory: a traversal path or an oversized archive must
be refused before any key is formed or any entry is read."""

import io
import zipfile

import pytest
from agentarea_agents.application import skill_package_limits as limits
from agentarea_agents.application.skill_package_limits import check_zip_budget, safe_package_path


@pytest.mark.parametrize(
    "path",
    ["../../other-ws/skill/SKILL.md", "a/../../b", "a//b", "./SKILL.md", "a\\b"],
)
def test_traversal_and_irregular_paths_are_refused(path: str) -> None:
    with pytest.raises(ValueError):
        safe_package_path(path)


def test_plain_nested_path_is_kept() -> None:
    assert safe_package_path("scripts/run.py") == "scripts/run.py"


def test_archive_over_the_uncompressed_budget_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(limits, "MAX_PACKAGE_TOTAL_BYTES", 1024)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", "x" * 2048)
    with zipfile.ZipFile(buffer) as zf, pytest.raises(ValueError, match="uncompressed"):
        check_zip_budget(zf)
