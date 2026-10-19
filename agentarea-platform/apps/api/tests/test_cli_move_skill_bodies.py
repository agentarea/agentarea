"""`agentarea-api skills move-bodies-to-packages` fails loud when a body did not move."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_api import cli
from click.testing import CliRunner


@pytest.fixture
def mover(monkeypatch):
    from agentarea_agents.application import skill_packages

    move = AsyncMock()
    monkeypatch.setattr(skill_packages, "move_all_bodies_to_packages", move)
    monkeypatch.setattr(cli, "Database", MagicMock())
    monkeypatch.setattr(cli, "get_db_settings", MagicMock())
    return move


def test_reports_what_it_moved(mover):
    mover.return_value = (3, 0)

    result = CliRunner().invoke(cli.cli, ["skills", "move-bodies-to-packages"])

    assert result.exit_code == 0, result.output
    assert "Moved 3 skill bodies into packages; 0 failed" in result.output


def test_a_body_that_did_not_move_fails_the_command(mover):
    mover.return_value = (2, 1)

    result = CliRunner().invoke(cli.cli, ["skills", "move-bodies-to-packages"])

    assert result.exit_code == 1
