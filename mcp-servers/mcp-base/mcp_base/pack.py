"""Build a deterministic MCP package layer inside the mcp-base image."""

from __future__ import annotations

import configparser
import contextlib
import hashlib
import io
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import anyio

logger = logging.getLogger("mcp-base.pack")

PACK_ENV_PREFIX = "MCP_BASE_PACK_"
BRIDGE_ENV_NAMES = frozenset({"PORT", "MCP_BASE_STARTUP_TIMEOUT"})
DEFAULT_SMOKE_TIMEOUT = 120.0
PACKAGE_DIR = Path("/tmp/mcp-pkg")


@dataclass(frozen=True)
class PackConfig:
    ecosystem: str
    package: str
    version: str
    executable: str
    arguments: tuple[str, ...]
    smoke_timeout: float
    port: int


@dataclass(frozen=True)
class PackResult:
    report: dict[str, Any]
    layer_path: Path | None
    workdir: Path


def _tail(value: str, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def _command_output(completed: subprocess.CompletedProcess[str]) -> str:
    parts = [part for part in (completed.stdout, completed.stderr) if part]
    return "\n".join(parts)


class CommandError(RuntimeError):
    """A subprocess failure retaining the command output for the report."""

    def __init__(self, message: str, output: str):
        super().__init__(message)
        self.output = output


def _run(command: Sequence[str], *, env: Mapping[str, str]) -> str:
    logger.info("running %s", " ".join(command))
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            cwd="/tmp",
            env=dict(env),
            text=True,
            errors="replace",
        )
    except OSError as exc:
        raise CommandError(f"could not run {' '.join(command)}: {exc}", "") from exc
    output = _command_output(completed)
    if completed.returncode != 0:
        detail = _tail(output).strip()
        suffix = f": {detail}" if detail else ""
        raise CommandError(
            f"command {' '.join(command)} exited with status {completed.returncode}{suffix}",
            output,
        )
    return output


def _validate_name(value: str, label: str) -> None:
    if not value or value in {".", ".."} or "\\" in value:
        raise ValueError(f"{label} must be a non-empty package name")


def _install_npm(config: PackConfig, package_dir: Path, env: Mapping[str, str]) -> str:
    _validate_name(config.package, "npm package")
    _validate_name(config.version, "npm version")
    package_spec = f"{config.package}@{config.version}"
    return _run(
        [
            "npm",
            "install",
            "--prefix",
            str(package_dir),
            "--omit=dev",
            "--no-audit",
            "--no-fund",
            "--ignore-scripts=false",
            package_spec,
        ],
        env=env,
    )


def _install_pypi(config: PackConfig, package_dir: Path, env: Mapping[str, str]) -> str:
    _validate_name(config.package, "PyPI project")
    _validate_name(config.version, "PyPI version")
    venv = package_dir / "venv"
    output = _run(
        [
            "uv",
            "venv",
            "--relocatable",
            "--python",
            "/usr/local/bin/python3",
            str(venv),
        ],
        env=env,
    )
    output += _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv / "bin" / "python"),
            f"{config.package}=={config.version}",
        ],
        env=env,
    )
    return output


def _package_json(package_dir: Path, package_name: str) -> dict[str, Any]:
    package_path = package_dir / "node_modules" / package_name / "package.json"
    try:
        with package_path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"installed npm package metadata is unavailable: {package_path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"installed npm package metadata is not an object: {package_path}")
    return value


def _entry_name(value: str, *, label: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ValueError(f"{label} must be an executable name")
    return value


def resolve_npm_entry(package_dir: Path, package_name: str, executable: str) -> Path:
    """Resolve an npm ``.bin`` entry according to the pack contract."""

    metadata = _package_json(package_dir, package_name)
    raw_bin = metadata.get("bin")
    if isinstance(raw_bin, str):
        unscoped = package_name.rsplit("/", 1)[-1]
        bins = {unscoped: raw_bin}
    elif isinstance(raw_bin, dict):
        bins = {str(name): value for name, value in raw_bin.items() if isinstance(value, str)}
    else:
        bins = {}
    if not bins:
        raise RuntimeError(f"npm package {package_name!r} does not declare a bin")

    if executable:
        selected = _entry_name(executable, label="npm executable")
    elif len(bins) == 1:
        selected = next(iter(bins))
    else:
        selected = package_name.rsplit("/", 1)[-1]
        if selected not in bins:
            raise RuntimeError(
                f"npm package {package_name!r} has multiple bins and no bin named {selected!r}"
            )

    entry = package_dir / "node_modules" / ".bin" / selected
    if not entry.is_file():
        raise RuntimeError(f"npm executable {selected!r} was not installed at {entry}")
    return entry


def _normalise_project_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _site_packages(package_dir: Path) -> Path:
    candidates = sorted((package_dir / "venv" / "lib").glob("python*/site-packages"))
    if not candidates:
        raise RuntimeError(f"Python site-packages was not installed under {package_dir / 'venv'}")
    return candidates[0]


def _metadata_name(metadata_file: Path) -> str | None:
    try:
        for line in metadata_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("name:"):
                return line.partition(":")[2].strip()
    except OSError:
        return None
    return None


def _console_scripts(dist_info: Path) -> dict[str, str]:
    entry_points = dist_info / "entry_points.txt"
    if not entry_points.is_file():
        return {}
    parser = configparser.RawConfigParser()
    try:
        parser.read(entry_points, encoding="utf-8")
    except (configparser.Error, OSError):
        return {}
    if not parser.has_section("console_scripts"):
        return {}
    return {name: value for name, value in parser.items("console_scripts")}


def _python_console_scripts(package_dir: Path, package_name: str) -> dict[str, str]:
    wanted = _normalise_project_name(package_name)
    scripts: dict[str, str] = {}
    for metadata_dir in sorted(_site_packages(package_dir).glob("*.dist-info")):
        name = _metadata_name(metadata_dir / "METADATA")
        if name is None:
            continue
        if _normalise_project_name(name) == wanted:
            scripts.update(_console_scripts(metadata_dir))
    for metadata_dir in sorted(_site_packages(package_dir).glob("*.egg-info")):
        name = _metadata_name(metadata_dir / "PKG-INFO")
        if name is None:
            continue
        if _normalise_project_name(name) == wanted:
            scripts.update(_console_scripts(metadata_dir))
    return scripts


def resolve_python_entry(package_dir: Path, package_name: str, executable: str) -> Path:
    """Resolve a Python console script from the installed project."""

    script_dir = package_dir / "venv" / "bin"
    if executable:
        selected = _entry_name(executable, label="Python executable")
    else:
        scripts = _python_console_scripts(package_dir, package_name)
        names = list(scripts)
        candidates = [
            _normalise_project_name(package_name),
            package_name.lower().replace("_", "-"),
            package_name.lower(),
        ]
        selected = next((candidate for candidate in candidates if candidate in scripts), None)
        if selected is None and len(names) == 1:
            selected = names[0]
        if selected is None:
            raise RuntimeError(
                f"Python project {package_name!r} has no uniquely resolvable console script"
            )
    entry = script_dir / selected
    if not entry.is_file():
        raise RuntimeError(f"Python executable {selected!r} was not installed at {entry}")
    return entry


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def detect_outside_writes(
    marker: Path,
    *,
    roots: Iterable[Path],
    excluded: Iterable[Path],
    limit: int = 50,
) -> list[str]:
    """List regular files and symlinks written after ``marker``."""

    marker_mtime = marker.stat().st_mtime_ns
    excluded_paths = [path.absolute() for path in excluded]
    found: list[str] = []
    visited_roots: set[Path] = set()

    def inspect(path: Path) -> None:
        absolute = path.absolute()
        if absolute in visited_roots:
            return
        visited_roots.add(absolute)
        try:
            root_stat = absolute.lstat()
        except OSError:
            return
        if any(_is_under(absolute, excluded_root) for excluded_root in excluded_paths):
            return
        if stat.S_ISLNK(root_stat.st_mode) or stat.S_ISREG(root_stat.st_mode):
            if root_stat.st_mtime_ns > marker_mtime:
                found.append(str(absolute))
            return
        if not stat.S_ISDIR(root_stat.st_mode):
            return
        try:
            entries = sorted(os.scandir(absolute), key=lambda entry: entry.name)
        except OSError:
            return
        for entry in entries:
            if len(found) >= limit:
                return
            child = Path(entry.path)
            if any(_is_under(child, excluded_root) for excluded_root in excluded_paths):
                continue
            try:
                child_stat = child.lstat()
            except OSError:
                continue
            if stat.S_ISDIR(child_stat.st_mode) and not stat.S_ISLNK(child_stat.st_mode):
                inspect(child)
            elif (stat.S_ISLNK(child_stat.st_mode) or stat.S_ISREG(child_stat.st_mode)) and (
                child_stat.st_mtime_ns > marker_mtime
            ):
                found.append(str(child.absolute()))

    for root in roots:
        if len(found) >= limit:
            break
        inspect(root)
    return sorted(found)[:limit]


def _fresh_child_dirs(workdir: Path) -> tuple[Path, Path, Path, Path]:
    home = workdir / "child-home"
    npm_cache = workdir / "child-npm-cache"
    uv_cache = workdir / "child-uv-cache"
    xdg_cache = workdir / "child-xdg-cache"
    for path in (home, npm_cache, uv_cache, xdg_cache):
        path.mkdir(parents=True, exist_ok=True)
    return home, npm_cache, uv_cache, xdg_cache


def build_child_environment(source: Mapping[str, str], workdir: Path) -> dict[str, str]:
    """Build the offline smoke-test environment without pack control variables."""

    environment = {
        key: value
        for key, value in source.items()
        if not key.startswith(PACK_ENV_PREFIX) and key not in BRIDGE_ENV_NAMES
    }
    environment.pop("NPM_CONFIG_CACHE", None)
    home, npm_cache, uv_cache, xdg_cache = _fresh_child_dirs(workdir)
    environment.update(
        {
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "all_proxy": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "no_proxy": "",
            "npm_config_offline": "true",
            "UV_OFFLINE": "1",
            "PIP_NO_INDEX": "1",
            "HOME": str(home),
            "npm_config_cache": str(npm_cache),
            "UV_CACHE_DIR": str(uv_cache),
            "XDG_CACHE_HOME": str(xdg_cache),
        }
    )
    return environment


def _iter_tree(root: Path) -> list[tuple[str, Path, os.stat_result]]:
    entries: list[tuple[str, Path, os.stat_result]] = [
        ("opt", root, root.lstat()),
        ("opt/mcp-pkg", root, root.lstat()),
    ]

    def visit(directory: Path, relative: str) -> None:
        try:
            children = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise RuntimeError(f"could not read package directory {directory}: {exc}") from exc
        for child in children:
            path = Path(child.path)
            child_relative = f"{relative}/{child.name}"
            try:
                child_stat = path.lstat()
            except OSError as exc:
                raise RuntimeError(f"could not stat package entry {path}: {exc}") from exc
            entries.append((child_relative, path, child_stat))
            if stat.S_ISDIR(child_stat.st_mode) and not stat.S_ISLNK(child_stat.st_mode):
                visit(path, child_relative)

    visit(root, "opt/mcp-pkg")
    return sorted(entries, key=lambda item: item[0])


def _tar_info(name: str, source: Path, source_stat: os.stat_result) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.mode = stat.S_IMODE(source_stat.st_mode)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.pax_headers = {}
    if stat.S_ISDIR(source_stat.st_mode):
        info.type = tarfile.DIRTYPE
    elif stat.S_ISLNK(source_stat.st_mode):
        info.type = tarfile.SYMTYPE
        info.linkname = os.readlink(source)
    elif stat.S_ISREG(source_stat.st_mode):
        info.type = tarfile.REGTYPE
        info.size = source_stat.st_size
    else:
        raise RuntimeError(f"unsupported package entry type: {source}")
    return info


def build_layer(package_dir: Path, layer_path: Path) -> tuple[str, int]:
    """Create a deterministic uncompressed tar layer and return hash and size."""

    entries = _iter_tree(package_dir)
    layer_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(layer_path, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, source, source_stat in entries:
            info = _tar_info(name, source, source_stat)
            if info.isreg():
                with source.open("rb") as stream:
                    archive.addfile(info, stream)
            else:
                archive.addfile(info)

    digest = hashlib.sha256()
    size = 0
    with layer_path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


async def _smoke_async(command: Sequence[str], env: Mapping[str, str], timeout: float) -> int:
    from mcp import Client, StdioServerParameters

    params = StdioServerParameters(command=command[0], args=list(command[1:]), env=dict(env))
    with anyio.fail_after(timeout):
        async with Client(params, mode="legacy") as child:
            result = await child.list_tools()
            return len(result.tools)


def smoke_test(command: Sequence[str], env: Mapping[str, str], timeout: float) -> tuple[int, str]:
    """Initialize a child and list its tools through the MCP stdio client."""

    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            tools = anyio.run(_smoke_async, list(command), dict(env), timeout)
    except BaseException as exc:
        detail = _tail(stderr.getvalue()).strip()
        if detail:
            raise RuntimeError(f"MCP smoke test failed: {exc}; child stderr: {detail}") from exc
        raise RuntimeError(f"MCP smoke test failed: {exc}") from exc
    return tools, stderr.getvalue()


def _config_from_environment(arguments: Sequence[str]) -> PackConfig:
    ecosystem = os.environ.get("MCP_BASE_PACK_ECOSYSTEM", "")
    package = os.environ.get("MCP_BASE_PACK_PACKAGE", "")
    version = os.environ.get("MCP_BASE_PACK_VERSION", "")
    executable = os.environ.get("MCP_BASE_PACK_EXECUTABLE", "")
    timeout_raw = os.environ.get("MCP_BASE_PACK_SMOKE_TIMEOUT", str(DEFAULT_SMOKE_TIMEOUT))
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise ValueError("MCP_BASE_PACK_SMOKE_TIMEOUT must be a number") from exc
    if timeout <= 0:
        raise ValueError("MCP_BASE_PACK_SMOKE_TIMEOUT must be greater than zero")
    try:
        port = int(os.environ.get("PORT", "8080"))
    except ValueError as exc:
        raise ValueError("PORT must be an integer") from exc
    if port < 1 or port > 65535:
        raise ValueError("PORT must be between 1 and 65535")
    return PackConfig(ecosystem, package, version, executable, tuple(arguments), timeout, port)


def _base_report(config: PackConfig) -> dict[str, Any]:
    return {
        "ok": False,
        "ecosystem": config.ecosystem,
        "package": config.package,
        "version": config.version,
        "entrypoint": [],
        "tools": 0,
        "outside_writes": [],
        "error": None,
        "log_tail": "",
        "layer": None,
    }


def run_pack(arguments: Sequence[str]) -> PackResult:
    """Install, smoke-test and package one requested MCP distribution."""

    try:
        config = _config_from_environment(arguments)
    except ValueError as exc:
        workdir = Path(tempfile.mkdtemp(prefix="mcp-pack-", dir="/tmp"))
        report = {
            "ok": False,
            "ecosystem": os.environ.get("MCP_BASE_PACK_ECOSYSTEM", ""),
            "package": os.environ.get("MCP_BASE_PACK_PACKAGE", ""),
            "version": os.environ.get("MCP_BASE_PACK_VERSION", ""),
            "entrypoint": [],
            "tools": 0,
            "outside_writes": [],
            "error": str(exc),
            "log_tail": "",
            "layer": None,
        }
        return PackResult(report, None, workdir)

    workdir = Path(tempfile.mkdtemp(prefix="mcp-pack-", dir="/tmp"))
    package_dir = PACKAGE_DIR
    if package_dir.is_symlink() or package_dir.is_file():
        package_dir.unlink()
    elif package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)
    marker = workdir / "install.marker"
    marker.touch()
    report = _base_report(config)
    output = ""
    logger.info("packing %s %s@%s", config.ecosystem, config.package, config.version)

    try:
        install_env = os.environ.copy()
        if config.ecosystem == "npm":
            output = _install_npm(config, package_dir, install_env)
        elif config.ecosystem == "pypi":
            output = _install_pypi(config, package_dir, install_env)
        else:
            raise RuntimeError(f"unsupported package ecosystem: {config.ecosystem!r}")

        cache_roots = [
            Path(value)
            for key, value in os.environ.items()
            if key in {"NPM_CONFIG_CACHE", "npm_config_cache", "UV_CACHE_DIR", "uv_cache_dir"}
            and value
        ]
        roots = [Path("/tmp")]
        home_value = os.environ.get("HOME")
        if home_value and home_value != "/tmp":
            roots.append(Path(home_value))
        outside = detect_outside_writes(
            marker,
            roots=roots,
            excluded=[package_dir, workdir, *cache_roots],
        )
        report["outside_writes"] = outside
        if outside:
            listed = ", ".join(outside[:3])
            raise RuntimeError(
                f"installation wrote outside the package directory: {listed}; "
                "a custom image FROM agentarea/agentarea-mcp-base is required"
            )

        if config.ecosystem == "npm":
            entry = resolve_npm_entry(package_dir, config.package, config.executable)
        else:
            entry = resolve_python_entry(package_dir, config.package, config.executable)
        final_entry = str(Path("/opt/mcp-pkg") / entry.relative_to(package_dir))
        report["entrypoint"] = [final_entry]
        child_env = build_child_environment(os.environ, workdir)
        smoke_tools, smoke_output = smoke_test([str(entry), *config.arguments], child_env, config.smoke_timeout)
        output += smoke_output
        report["tools"] = smoke_tools

        layer_path = workdir / "layer.tar"
        digest, size = build_layer(package_dir, layer_path)
        report["layer"] = {"sha256": digest, "size": size}
        report["ok"] = True
        report["error"] = None
        return PackResult(report, layer_path, workdir)
    except BaseException as exc:
        if isinstance(exc, CommandError):
            output += exc.output
        output = f"{output}\n{exc}" if output else str(exc)
        report["error"] = str(exc)
        return PackResult(report, None, workdir)
    finally:
        report["log_tail"] = _tail(output)

class _PackHandler(BaseHTTPRequestHandler):
    server: "_PackHTTPServer"

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_bytes(200, b"ok", "text/plain; charset=utf-8")
            return
        if self.path == "/report":
            body = json.dumps(self.server.report, separators=(",", ":")).encode("utf-8")
            self._send_bytes(200, body, "application/json")
            return
        if self.path == "/layer.tar":
            if not self.server.report["ok"] or self.server.layer_path is None:
                self._send_bytes(404, b"not found", "text/plain; charset=utf-8")
                return
            try:
                body = self.server.layer_path.read_bytes()
            except OSError:
                self._send_bytes(404, b"not found", "text/plain; charset=utf-8")
                return
            self._send_bytes(200, body, "application/x-tar")
            return
        self._send_bytes(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, format: str, *args: object) -> None:
        logger.info("HTTP " + format, *args)


class _PackHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], report: dict[str, Any], layer_path: Path | None):
        self.report = report
        self.layer_path = layer_path
        super().__init__(address, _PackHandler)


def serve(arguments: Sequence[str]) -> None:
    result = run_pack(arguments)
    port_raw = os.environ.get("PORT", "8080")
    try:
        port = int(port_raw)
    except ValueError:
        port = 8080
    logger.info("pack report ready on port %d (ok=%s)", port, result.report["ok"])
    server = _PackHTTPServer(("0.0.0.0", port), result.report, result.layer_path)  # noqa: S104
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("pack server stopped")
    finally:
        server.server_close()
        shutil.rmtree(result.workdir, ignore_errors=True)
        if PACKAGE_DIR.exists() and not PACKAGE_DIR.is_symlink():
            shutil.rmtree(PACKAGE_DIR, ignore_errors=True)


def main(arguments: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="[mcp-base] %(message)s")
    serve(tuple(sys.argv[1:] if arguments is None else arguments))
