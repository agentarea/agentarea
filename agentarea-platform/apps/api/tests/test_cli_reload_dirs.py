"""`serve --reload` watches the API package and the workspace libs it imports."""

from pathlib import Path

import click
import pytest

from agentarea_api.cli import reload_dirs


def test_watches_the_api_package_and_the_workspace_libs(tmp_path: Path):
    package = tmp_path / "apps" / "api" / "agentarea_api"
    package.mkdir(parents=True)
    (tmp_path / "libs").mkdir()

    assert reload_dirs(package / "cli.py") == [str(package), str(tmp_path / "libs")]


def test_refuses_to_reload_without_the_libs_dir(tmp_path: Path):
    package = tmp_path / "apps" / "api" / "agentarea_api"
    package.mkdir(parents=True)

    with pytest.raises(click.UsageError, match="libs"):
        reload_dirs(package / "cli.py")


def test_resolves_this_checkout():
    import agentarea_api.cli

    package, libs = reload_dirs(Path(agentarea_api.cli.__file__))

    assert Path(package, "cli.py").is_file()
    assert Path(libs, "mcp", "agentarea_mcp").is_dir()
