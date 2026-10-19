"""`agentarea-api skills repin-catalog-installs` says what it did to each skill and
fails when a repin failed; a gone or edited skill is reported, not a failure.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_agents.application.skill_service import SkillRepinResult
from agentarea_api import cli
from click.testing import CliRunner


@pytest.fixture
def repin(monkeypatch):
    from agentarea_agents.application import skill_service

    monkeypatch.setenv("AGENTAREA_S3_ACCESS_KEY", "key")
    monkeypatch.setenv("AGENTAREA_S3_SECRET_KEY", "secret")
    run = AsyncMock()
    monkeypatch.setattr(skill_service, "repin_all_catalog_installs", run)
    monkeypatch.setattr(cli, "Database", MagicMock())
    monkeypatch.setattr(cli, "get_db_settings", MagicMock())
    return run


def _invoke(*args):
    return CliRunner().invoke(cli.cli, ["skills", "repin-catalog-installs", *args])


def test_reports_each_skill_and_a_summary(repin):
    repin.return_value = [
        ("ws-1", SkillRepinResult("s1", "pdf", "repinned")),
        ("ws-1", SkillRepinResult("s2", "xlsx", "edited")),
        ("ws-2", SkillRepinResult("s3", "docx", "gone", error="its catalog item is no longer listed")),
    ]

    result = _invoke()

    assert result.exit_code == 0, result.output
    assert "repinned  ws-1/s1  pdf" in result.output
    assert "gone  ws-2/s3  docx: its catalog item is no longer listed" in result.output
    assert "1 repinned, 1 edited, 1 gone" in result.output
    assert repin.await_args.kwargs["dry_run"] is False


def test_a_dry_run_is_passed_through(repin):
    repin.return_value = [("ws-1", SkillRepinResult("s1", "pdf", "would_repin"))]

    result = _invoke("--dry-run")

    assert result.exit_code == 0, result.output
    assert repin.await_args.kwargs["dry_run"] is True
    assert "1 would_repin" in result.output


def test_a_failed_repin_fails_the_command(repin):
    repin.return_value = [("ws-1", SkillRepinResult("s1", "", "failed", error="S3 is down"))]

    result = _invoke()

    assert result.exit_code == 1
    assert "failed  ws-1/s1" in result.output
