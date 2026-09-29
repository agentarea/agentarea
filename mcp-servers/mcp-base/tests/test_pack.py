from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path


from mcp_base import pack


def test_layer_is_rerooted_sorted_and_normalized(tmp_path: Path) -> None:
    package = tmp_path / "mcp-pkg"
    package.mkdir()
    (package / "z.txt").write_text("z", encoding="utf-8")
    (package / "a.txt").write_text("a", encoding="utf-8")
    nested = package / "nested"
    nested.mkdir()
    (nested / "value").write_text("nested", encoding="utf-8")
    (package / "link").symlink_to("a.txt")
    (package / "hard").hardlink_to(package / "a.txt")
    os.chmod(package / "a.txt", 0o640)

    layer = tmp_path / "layer.tar"
    pack.build_layer(package, layer)

    with tarfile.open(layer) as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == sorted(member.name for member in members)
        assert {member.name for member in members[:2]} == {"opt", "opt/mcp-pkg"}
        assert all(member.uid == 0 and member.gid == 0 for member in members)
        assert all(member.uname == "" and member.gname == "" for member in members)
        assert all(member.mtime == 0 for member in members)
        assert members[0].name == "opt"

        link = archive.getmember("opt/mcp-pkg/link")
        assert link.issym()
        assert link.linkname == "a.txt"

        hard = archive.getmember("opt/mcp-pkg/hard")
        assert hard.isreg()
        assert not hard.islnk()
        assert archive.extractfile(hard).read() == b"a"


def test_outside_writes_report_files_but_not_package_or_caches(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    marker.write_text("marker", encoding="utf-8")
    marker_mtime = marker.stat().st_mtime_ns

    package = tmp_path / "mcp-pkg"
    package.mkdir()
    (package / "inside").write_text("inside", encoding="utf-8")
    npm_cache = tmp_path / "npm-cache"
    npm_cache.mkdir()
    (npm_cache / "cache-entry").write_text("cache", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.write_text("unexpected", encoding="utf-8")
    os.utime(outside, ns=(marker_mtime + 1, marker_mtime + 1))

    writes = pack.detect_outside_writes(
        marker,
        roots=[tmp_path],
        excluded=[package, npm_cache, marker.parent / "work"],
    )

    assert writes == [str(outside)]


def test_npm_executable_resolution_prefers_unscoped_bin_name(tmp_path: Path) -> None:
    package = tmp_path / "mcp-pkg"
    package_json = package / "node_modules" / "@scope" / "tool" / "package.json"
    package_json.parent.mkdir(parents=True)
    package_json.write_text(
        json.dumps({"name": "@scope/tool", "bin": {"other": "cli.js", "tool": "main.js"}}),
        encoding="utf-8",
    )
    bin_dir = package / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (package / "node_modules" / "@scope" / "tool" / "main.js").write_text("", encoding="utf-8")
    (bin_dir / "tool").symlink_to("../@scope/tool/main.js")

    result = pack.resolve_npm_entry(package, "@scope/tool", "")

    assert result == package / "node_modules" / ".bin" / "tool"


def test_npm_executable_resolution_accepts_only_bin(tmp_path: Path) -> None:
    package = tmp_path / "mcp-pkg"
    package_json = package / "node_modules" / "one" / "package.json"
    package_json.parent.mkdir(parents=True)
    package_json.write_text(json.dumps({"name": "one", "bin": "cli.js"}), encoding="utf-8")
    bin_dir = package / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (package / "node_modules" / "one" / "cli.js").write_text("", encoding="utf-8")
    (bin_dir / "one").symlink_to("../one/cli.js")

    result = pack.resolve_npm_entry(package, "one", "")

    assert result == bin_dir / "one"


def test_python_executable_resolution_uses_project_console_script(tmp_path: Path) -> None:
    package = tmp_path / "mcp-pkg"
    site = package / "venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    dist_info = site / "mcp_server_time-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Name: mcp-server-time\n", encoding="utf-8")
    (dist_info / "entry_points.txt").write_text(
        "[console_scripts]\nmcp-server-time = mcp_server_time:main\n", encoding="utf-8"
    )
    script = package / "venv" / "bin" / "mcp-server-time"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/local/bin/python3\n", encoding="utf-8")

    result = pack.resolve_python_entry(package, "mcp-server-time", "")

    assert result == script


def test_child_environment_excludes_pack_control_variables(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    source = {
        "MCP_BASE_PACK_ECOSYSTEM": "npm",
        "MCP_BASE_PACK_PACKAGE": "pkg",
        "MCP_BASE_PACK_VERSION": "1.0.0",
        "MCP_BASE_PACK_EXECUTABLE": "pkg",
        "MCP_BASE_PACK_SMOKE_TIMEOUT": "120",
        "PORT": "8080",
        "MCP_BASE_STARTUP_TIMEOUT": "300",
        "KEEP": "yes",
    }

    child = pack.build_child_environment(source, workdir)

    assert all(not key.startswith("MCP_BASE_PACK_") for key in child)
    assert "PORT" not in child
    assert "MCP_BASE_STARTUP_TIMEOUT" not in child
    assert child["KEEP"] == "yes"
    assert child["HOME"].startswith(str(workdir))
    assert child["npm_config_cache"].startswith(str(workdir))
    assert child["UV_CACHE_DIR"].startswith(str(workdir))
    assert child["XDG_CACHE_HOME"].startswith(str(workdir))
    assert child["HTTP_PROXY"] == "http://127.0.0.1:9"
    assert child["NO_PROXY"] == ""
