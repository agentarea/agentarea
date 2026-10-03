"""Tests for command-to-package-image conversion and its monitor sweep."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from agentarea_mcp.application.service import _server_transport_spec
from agentarea_mcp.application.validation_service import MCPConfigurationValidator
from agentarea_mcp.container_monitor import MCPContainerMonitor
from agentarea_mcp.package_import import import_package_image
from agentarea_mcp.schemas.dto import MCPServerInstanceCreate
from agentarea_mcp.transport_spec import merge_transport_spec


class _Begin:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Result:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class _Server:
    def __init__(self, row, *, cmd=None):
        self.id = row.server_spec_id
        self.json_spec = {}
        self.remote_url = None
        self.cmd = cmd
        self.docker_image_url = None


class _Session:
    def __init__(self, row, *, server=None):
        self.row = row
        self.server = server or self._default_server(row)
        self.execute_calls = []

    @staticmethod
    def _default_server(row):
        spec = row.json_spec or {}
        command = spec.get("command")
        args = spec.get("args", [])
        cmd = [command, *args] if isinstance(command, str) and isinstance(args, list) else None
        return _Server(row, cmd=cmd)

    def begin(self):
        return _Begin()

    async def execute(self, statement):
        statement_text = str(statement)
        self.execute_calls.append(statement_text)
        if "mcp_servers" in statement_text:
            return _Result(self.server)
        return _Result(self.row)


class _Settings:
    MCP_MANAGER_URL = "http://manager"
    MCP_CLIENT_TIMEOUT = 30

    @staticmethod
    def manager_retire_url(instance_id):
        return f"http://manager/mcp/{instance_id}"

    @staticmethod
    def manager_gateway_headers():
        return {"X-AgentArea-Manager-Authorization": "Bearer manager-secret"}


class _Row:
    def __init__(self, json_spec: dict):
        self.id = uuid4()
        self.name = "npm-server"
        self.server_spec_id = str(uuid4())
        self.verification = {"status": "succeeded"}
        self.json_spec = json_spec
        self.set_events: list[str] = []

    def __setattr__(self, name, value):
        if name == "json_spec" and "set_events" in self.__dict__:
            self.set_events.append("persist")
        object.__setattr__(self, name, value)


def _patch_http(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr("agentarea_mcp.package_import.httpx.AsyncClient", factory)
    monkeypatch.setattr(
        "agentarea_mcp.package_import.get_settings", lambda: SimpleNamespace(mcp=_Settings())
    )


@pytest.mark.asyncio
async def test_import_200_converts_spec_and_retires_before_persisting(monkeypatch):
    old_spec = {
        "type": "command",
        "command": "npx",
        "args": ["-y", "@acme/server", "--stdio"],
        "environment": {"MODE": "prod"},
        "env_vars": ["TOKEN"],
        "network": {"scope": "private"},
        "cmd": ["obsolete"],
        "package_import": {"status": "unavailable", "error": "old", "at": "old"},
    }
    row = _Row(old_spec)
    session = _Session(row)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            assert request.url.path == "/packages/import"
            assert json.loads(request.content) == {"instance_id": str(row.id)}
            assert request.headers["X-AgentArea-Manager-Authorization"] == "Bearer manager-secret"
            return httpx.Response(
                200,
                json={
                    "image": "ghcr.io/acme/server@sha256:" + "a" * 64,
                    "command": ["/opt/mcp-pkg/bin/server", "--stdio"],
                    "port": 8080,
                    "package": {"ecosystem": "npm", "name": "@acme/server", "version": "1.2.3"},
                    "built": True,
                },
            )
        assert request.method == "DELETE"
        assert request.url.path == f"/mcp/{row.id}"
        calls.append("retire")
        return httpx.Response(204)

    _patch_http(monkeypatch, handler)
    monkeypatch.setattr("agentarea_mcp.package_import.get_database", lambda: SimpleNamespace())

    result = await import_package_image(row.id, session=session)

    assert result is None
    assert calls == ["POST", "DELETE", "retire"]
    assert row.json_spec == {
        "environment": {"MODE": "prod"},
        "env_vars": ["TOKEN"],
        "network": {"scope": "private"},
        "type": "docker",
        "image": "ghcr.io/acme/server@sha256:" + "a" * 64,
        "port": 8080,
        "command": ["/opt/mcp-pkg/bin/server", "--stdio"],
        "package": {"ecosystem": "npm", "name": "@acme/server", "version": "1.2.3"},
        "source": {
            "type": "command",
            "command": "npx",
            "args": ["-y", "@acme/server", "--stdio"],
        },
    }
    assert row.set_events == ["persist"]


@pytest.mark.asyncio
async def test_import_records_effective_source_from_server_command(monkeypatch):
    row = _Row({"type": "command", "environment": {"MODE": "prod"}})
    server = _Server(row, cmd=["uvx", "mcp-server-time", "--stdio"])
    session = _Session(row, server=server)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "image": "ghcr.io/acme/server@sha256:" + "c" * 64,
                    "command": ["/opt/mcp-pkg/bin/server"],
                    "port": 8080,
                    "package": {"ecosystem": "pypi", "name": "mcp-server-time"},
                },
            )
        return httpx.Response(204)

    _patch_http(monkeypatch, handler)
    await import_package_image(row.id, session=session)

    assert row.json_spec["source"] == {
        "type": "command",
        "command": "uvx",
        "args": ["mcp-server-time", "--stdio"],
    }


def test_converted_instance_merge_drops_server_transport_fields():
    merged = merge_transport_spec(
        {
            "type": "command",
            "command": "uvx",
            "args": ["mcp-server-time"],
            "endpoint_url": "http://server.example",
            "catalog_name": "time",
        },
        {
            "type": "docker",
            "image": "ghcr.io/acme/server@sha256:" + "d" * 64,
            "command": ["/opt/mcp-pkg/bin/server"],
            "port": 8080,
            "package": {"name": "mcp-server-time"},
        },
    )

    assert merged["type"] == "docker"
    assert merged["image"].endswith("d" * 64)
    assert merged["command"] == ["/opt/mcp-pkg/bin/server"]
    assert "args" not in merged
    assert "endpoint_url" not in merged
    assert merged["catalog_name"] == "time"


@pytest.mark.asyncio
async def test_import_422_records_rejected_without_retirement(monkeypatch):
    row = _Row({"type": "command", "command": "uvx", "args": ["--from", "pkg", "pkg"]})
    session = _Session(row)
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(422, json={"error": "unsupported package spec"})

    _patch_http(monkeypatch, handler)
    await import_package_image(row.id, session=session)

    assert methods == ["POST"]
    assert row.json_spec["type"] == "command"
    assert row.json_spec["package_import"]["status"] == "rejected"
    assert row.json_spec["package_import"]["error"] == "unsupported package spec"


@pytest.mark.asyncio
async def test_import_503_records_unavailable(monkeypatch):
    row = _Row({"type": "command", "command": "npx", "args": ["server"]})
    session = _Session(row)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "registry unavailable"})

    _patch_http(monkeypatch, handler)
    await import_package_image(row.id, session=session)

    assert row.json_spec["package_import"]["status"] == "unavailable"
    assert row.json_spec["package_import"]["error"] == "registry unavailable"


def test_converted_docker_spec_passes_create_and_transport_validation():
    spec = {
        "type": "docker",
        "image": "registry.example/mcp/server@sha256:" + "b" * 64,
        "command": ["/opt/mcp-pkg/bin/server", "--stdio"],
        "port": 8080,
        "package": {"ecosystem": "pypi", "name": "mcp-server", "version": "1.0.0"},
        "source": {"type": "command", "command": "uvx", "args": ["mcp-server"]},
        "environment": {"TOKEN": "secret"},
    }

    assert MCPConfigurationValidator.validate_json_spec(spec) == []
    payload = MCPServerInstanceCreate(name="converted", server_spec_id=uuid4(), json_spec=spec)
    assert payload.json_spec == spec
    assert (
        _server_transport_spec(
            SimpleNamespace(json_spec=spec, remote_url=None, cmd=None, docker_image_url=None)
        )
        == spec
    )


@pytest.mark.asyncio
async def test_monitor_package_sweep_uses_effective_server_command_and_is_sequential(
    monkeypatch,
):
    monitor = MCPContainerMonitor(check_interval=30)
    candidate_ids = [uuid4(), uuid4(), uuid4()]
    events: list[tuple[str, UUID]] = []
    active = 0

    async def fake_import(instance_id):
        nonlocal active
        active += 1
        events.append(("start", instance_id))
        assert active == 1
        await asyncio.sleep(0)
        active -= 1
        events.append(("finish", instance_id))

    monkeypatch.setattr("agentarea_mcp.container_monitor.import_package_image", fake_import)

    package_calls: list[tuple[object, int]] = []

    async def fake_candidates(session, *, limit):
        package_calls.append((session, limit))
        return [
            SimpleNamespace(
                id=instance_id,
                json_spec={},
                server_json_spec={},
                cmd=["uvx", "mcp-server-time"],
                remote_url=None,
                verification={"status": "succeeded"},
                workspace_id=uuid4(),
            )
            for instance_id in candidate_ids
        ]

    monkeypatch.setattr(
        "agentarea_mcp.container_monitor.MCPServerInstanceRepository.list_package_import_candidates",
        fake_candidates,
    )

    class _GCResult:
        rowcount = 0

    class _RowsResult:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class _SessionForSweep:
        def __init__(self):
            self.sql: list[str] = []

        def begin(self):
            return _Begin()

        async def execute(self, statement, params=None):
            statement_text = str(statement)
            self.sql.append(statement_text)
            if "in_progress" in statement_text:
                return _GCResult()
            return _RowsResult([])

        async def commit(self):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    sweep_session = _SessionForSweep()
    monkeypatch.setattr(
        "agentarea_mcp.container_monitor.get_database",
        lambda: SimpleNamespace(async_session_factory=lambda: sweep_session),
    )

    await monitor._tick()

    assert [instance_id for kind, instance_id in events if kind == "start"] == candidate_ids
    assert [kind for kind, _ in events] == [
        "start",
        "finish",
        "start",
        "finish",
        "start",
        "finish",
    ]
    assert package_calls == [(sweep_session, 3)]


@pytest.mark.asyncio
async def test_import_transport_error_records_unavailable(monkeypatch):
    row = _Row({"type": "command", "command": "npx", "args": ["server"]})
    session = _Session(row)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("manager down")

    _patch_http(monkeypatch, handler)
    await import_package_image(row.id, session=session)

    assert row.json_spec["package_import"]["status"] == "unavailable"
    assert "manager down" in row.json_spec["package_import"]["error"]


@pytest.mark.asyncio
async def test_import_timeout_records_unavailable(monkeypatch):
    row = _Row({"type": "command", "command": "npx", "args": ["server"]})
    session = _Session(row)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("manager timeout")

    _patch_http(monkeypatch, handler)
    await import_package_image(row.id, session=session)

    assert row.json_spec["package_import"]["status"] == "unavailable"
    assert "manager timeout" in row.json_spec["package_import"]["error"]


@pytest.mark.asyncio
async def test_retirement_conflict_retries_then_raises_retryable_conflict(monkeypatch):
    from agentarea_mcp.package_import import (
        MCPRuntimeRetirementConflictError,
        retire_runtime_before_mutation,
    )

    calls = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(409)

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    _patch_http(monkeypatch, handler)
    monkeypatch.setattr("agentarea_mcp.package_import.asyncio.sleep", fake_sleep)

    with pytest.raises(MCPRuntimeRetirementConflictError) as exc_info:
        await retire_runtime_before_mutation(uuid4())

    assert exc_info.value.status_code == 409
    assert calls > 3
    assert delays
    assert all(0 < delay <= 1 for delay in delays)
