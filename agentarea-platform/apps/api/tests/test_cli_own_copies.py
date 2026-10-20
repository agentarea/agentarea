"""The pre-package copies of workspace skills move into packages, then go on request."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_api import cli
from click.testing import CliRunner


@pytest.fixture
def packages(monkeypatch):
    monkeypatch.setenv("AGENTAREA_S3_ACCESS_KEY", "key")
    monkeypatch.setenv("AGENTAREA_S3_SECRET_KEY", "secret")
    from agentarea_agents.application import skill_packages

    move, delete = AsyncMock(), AsyncMock()
    monkeypatch.setattr(skill_packages, "move_all_own_copies_to_packages", move)
    monkeypatch.setattr(skill_packages, "delete_moved_own_copies", delete)
    monkeypatch.setattr(cli, "Database", MagicMock())
    monkeypatch.setattr(cli, "get_db_settings", MagicMock())
    return move, delete


def test_moving_reports_what_moved_and_fails_on_a_copy_that_did_not(packages):
    move, _ = packages
    move.return_value = (4, 0)
    ok = CliRunner().invoke(cli.cli, ["skills", "move-own-copies-to-packages"])
    move.return_value = (3, 1)
    failed = CliRunner().invoke(cli.cli, ["skills", "move-own-copies-to-packages"])

    assert ok.exit_code == 0, ok.output
    assert "Moved 4 skill copies into packages; 0 failed" in ok.output
    assert failed.exit_code == 1


@pytest.mark.parametrize(("args", "dry_run"), [([], False), (["--dry-run"], True)])
def test_deleting_moved_copies_says_how_many(packages, args, dry_run):
    _, delete = packages
    delete.return_value = (2, 5)

    result = CliRunner().invoke(cli.cli, ["skills", "delete-moved-own-copies", *args])

    assert result.exit_code == 0, result.output
    assert delete.await_args.kwargs == {"dry_run": dry_run}
    verb = "Would delete" if dry_run else "Deleted"
    assert f"{verb} 2 moved skill copies (5 files)" in result.output
