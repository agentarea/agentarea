"""`agentarea-api skills refresh-stub-installs` says what it did to each stub and
fails only when a refresh errored; a folder gone from GitHub or a refusal is reported.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_agents.application.skill_stub_refresh import StubRefreshResult
from agentarea_api import cli
from click.testing import CliRunner


@pytest.fixture
def refresh(monkeypatch):
    from agentarea_agents.application import skill_stub_refresh

    monkeypatch.setenv("AGENTAREA_S3_ACCESS_KEY", "key")
    monkeypatch.setenv("AGENTAREA_S3_SECRET_KEY", "secret")
    run = AsyncMock()
    monkeypatch.setattr(skill_stub_refresh, "refresh_all_stub_installs", run)
    monkeypatch.setattr(cli, "Database", MagicMock())
    monkeypatch.setattr(cli, "get_db_settings", MagicMock())
    return run


def _invoke(*args):
    return CliRunner().invoke(cli.cli, ["skills", "refresh-stub-installs", *args])


def test_reports_each_stub_and_a_summary(refresh):
    url = "https://github.com/o/r/tree/" + "1" * 40 + "/seo"
    refresh.return_value = [
        ("ws-1", StubRefreshResult("s1", "seo", "refreshed", source_url=url)),
        ("ws-1", StubRefreshResult("s2", "pdf", "not_found", detail="o/r/pdf is gone")),
        ("ws-2", StubRefreshResult("s3", "xlsx", "refused", detail="denied by registry:github")),
    ]

    result = _invoke()

    assert result.exit_code == 0, result.output
    assert f"refreshed  ws-1/s1  seo  {url}" in result.output
    assert "not_found  ws-1/s2  pdf: o/r/pdf is gone" in result.output
    assert "1 refreshed, 1 not_found, 1 refused" in result.output
    assert refresh.await_args.kwargs["dry_run"] is False


def test_a_dry_run_is_passed_through(refresh):
    refresh.return_value = [("ws-1", StubRefreshResult("s1", "seo", "would_refresh"))]

    result = _invoke("--dry-run")

    assert result.exit_code == 0, result.output
    assert refresh.await_args.kwargs["dry_run"] is True
    assert "1 would_refresh" in result.output


def test_nothing_to_refresh_says_so(refresh):
    refresh.return_value = []

    result = _invoke()

    assert result.exit_code == 0, result.output
    assert "No stub installs" in result.output


def test_an_errored_refresh_fails_the_command(refresh):
    refresh.return_value = [("ws-1", StubRefreshResult("s1", "", "error", detail="S3 is down"))]

    result = _invoke()

    assert result.exit_code == 1
    assert "error  ws-1/s1" in result.output
