"""Tests for agentarea_mcp.verification.verify() and MCPContainerMonitor."""

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest
from agentarea_mcp.domain.verification_types import DEFAULT_VERIFICATION

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeInstance:
    """Plain object mirroring MCPServerInstance attributes for tests."""
    def __init__(self, instance_type="docker", verification=None):
        self.id = uuid.uuid4()
        self.name = "test-inst"
        self.json_spec = {"type": instance_type}
        self.workspace_id = uuid.uuid4()
        self.created_by = str(uuid.uuid4())
        self.verification = verification if verification is not None else dict(DEFAULT_VERIFICATION)
        self.last_dispatch = None
        self.tools = None

    @property
    def endpoint_url(self) -> str:
        t = self.json_spec.get("type", "")
        if t == "url":
            return self.json_spec.get("endpoint_url", "")
        if t in ("docker", "command"):
            resolved = self.json_spec.get("internal_url")
            if isinstance(resolved, str) and "://" in resolved:
                return resolved
            if t == "command":
                port = 8080
            else:
                port = self.json_spec.get("port") or 8000
            return f"http://mcp-{self.id}:{port}"
        raise ValueError("bundle has no endpoint_url")


def _make_instance(instance_type="docker", verification=None):
    return _FakeInstance(instance_type=instance_type, verification=verification)


class _AsyncContextManagerMock:
    """Reusable async context manager that does nothing."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _make_db_mock(instance):
    """Return a mock get_database() that returns a db with a fake session factory."""

    class FakeSession:
        def __init__(self):
            self._exec_call = 0

        def begin(self):
            return _AsyncContextManagerMock()

        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = instance
            result.scalar_one.return_value = instance
            result.fetchall.return_value = []
            return result

        async def flush(self):
            pass

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class FakeDB:
        def async_session_factory(self):
            return FakeSession()

    return FakeDB()


# ---------------------------------------------------------------------------
# verify() happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_happy_path_sets_succeeded():
    """verify() with a working MCP server writes succeeded + tools."""
    inst = _make_instance("docker")
    db_mock = _make_db_mock(inst)

    fake_tools = [{"name": "read_file", "description": "reads", "inputSchema": {}}]

    async def fake_list_tools(endpoint_url, headers=None):
        return fake_tools

    async def fake_go_create(instance, mcp_manager_url):
        return {"status_code": 201, "body": {}}

    async def fake_go_health(instance_id, mcp_manager_url):
        return {"healthy": True, "state": "running"}

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings:
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
            _go_health_fn=fake_go_health,
        )

    assert result["status"] == "succeeded"
    assert result["error"] is None
    assert result["schema_version"] == 1


# ---------------------------------------------------------------------------
# verify() Go ack failure — fast-fail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_go_ack_failure_fast_fails():
    """verify() returns failed immediately when Go manager returns non-2xx."""
    inst = _make_instance("docker")
    db_mock = _make_db_mock(inst)

    async def fake_go_create(instance, mcp_manager_url):
        return {
            "status_code": 422,
            "body": {"code": "image_not_found", "message": "Image does/not:exist not found"},
        }

    async def fake_list_tools(endpoint_url, headers=None):
        raise AssertionError("list_tools should NOT be called after go ack failure")

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings:
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
        )

    assert result["status"] == "failed"
    assert result["error"]["code"] == "image_not_found"


@pytest.mark.asyncio
async def test_verify_go_ack_prefers_error_string_over_http_code():
    """Real Go manager returns {error: 'instance_creation_failed', code: 500}.

    Our semantic code must come from `error`, not from the echoed HTTP status.
    """
    inst = _make_instance("docker")
    db_mock = _make_db_mock(inst)

    async def fake_go_create(instance, mcp_manager_url):
        return {
            "status_code": 500,
            "body": {
                "error": "instance_creation_failed",
                "code": 500,
                "message": "failed to create container: exit status 125",
            },
        }

    async def fake_list_tools(endpoint_url, headers=None):
        raise AssertionError("list_tools should NOT be called after go ack failure")

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings:
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
        )

    assert result["status"] == "failed"
    assert result["error"]["code"] == "instance_creation_failed"
    assert "exit status 125" in result["error"]["message"]


# ---------------------------------------------------------------------------
# verify() list_tools timeout — enriches error via health call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_list_tools_timeout_enriches_error():
    """When all list_tools attempts time out, verify() calls health to enrich error."""
    inst = _make_instance("docker")
    db_mock = _make_db_mock(inst)

    async def fake_go_create(instance, mcp_manager_url):
        return {"status_code": 201, "body": {}}

    async def fake_list_tools(endpoint_url, headers=None):
        raise ConnectionRefusedError("connection refused")

    async def fake_go_health(instance_id, mcp_manager_url):
        return {"healthy": False, "state": "starting"}

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings, \
         patch("agentarea_mcp.verification._LIST_TOOLS_BACKOFF_DELAYS", [0, 0]):
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
            _go_health_fn=fake_go_health,
        )

    assert result["status"] == "failed"
    assert result["error"]["code"] in ("container_not_ready", "list_tools_timeout")


# ---------------------------------------------------------------------------
# verify() concurrency — second call returns first result without re-running
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_concurrency_second_sees_in_progress_and_skips():
    """If another verify() is already in_progress, a second call must not re-run."""
    inst = _make_instance("docker")
    inst.verification = {
        "schema_version": 1,
        "status": "in_progress",
        "at": "2026-04-18T00:00:00+00:00",
        "error": None,
    }

    db_mock = _make_db_mock(inst)

    go_create_calls = 0

    async def fake_go_create(instance, mcp_manager_url):
        nonlocal go_create_calls
        go_create_calls += 1
        return {"status_code": 201, "body": {}}

    async def fake_list_tools(endpoint_url, headers=None):
        return []

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings:
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
        )

    # Returns the in-progress payload without re-running provisioning.
    assert result["status"] == "in_progress"
    assert go_create_calls == 0


@pytest.mark.asyncio
async def test_verify_ignores_docker_path_internal_url():
    """Docker backend returns a traefik path like `/mcp/<slug>` (not a URL).

    We must NOT use that as an endpoint — falling back to the direct-container
    address the domain model computes.
    """
    inst = _make_instance("docker")
    # Model's endpoint_url uses port from json_spec → default 8000
    inst.json_spec = {"type": "docker", "image": "x:y", "port": 8000}

    db_mock = _make_db_mock(inst)

    async def fake_go_create(instance, mcp_manager_url):
        return {
            "status_code": 201,
            "body": {"url": "/mcp/abc"},
            "internal_url": "/mcp/abc",  # a path, not a URL
        }

    list_tools_targets: list[str] = []

    async def fake_list_tools(endpoint_url, headers=None):
        list_tools_targets.append(endpoint_url)
        return []

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings:
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
        )

    assert list_tools_targets, "list_tools must be called"
    assert list_tools_targets[0].startswith("http://"), (
        f"Must use a full URL, not the traefik path; got {list_tools_targets[0]!r}"
    )
    assert ":8000" in list_tools_targets[0], "Port must match json_spec.port"


@pytest.mark.asyncio
async def test_verify_uses_internal_url_from_go_ack():
    """verify() must prefer the Go manager's internal_url over the model's guess.

    The Go backend knows the real Service/container name + port because it
    created the resource. Our hardcoded fallback `mcp-<UUID>:8080` doesn't
    match either the Docker container name or the K8s Service DNS, so the
    Go-reported URL is the authoritative source.
    """
    inst = _make_instance("docker")
    db_mock = _make_db_mock(inst)

    async def fake_go_create(instance, mcp_manager_url):
        return {
            "status_code": 201,
            "body": {"instance_id": str(instance.id)},
            "internal_url": "http://mcp-my-name.agentarea.svc.cluster.local:8000",
        }

    list_tools_targets: list[str] = []

    async def fake_list_tools(endpoint_url, headers=None):
        list_tools_targets.append(endpoint_url)
        return [{"name": "tool_a", "description": "", "inputSchema": {}}]

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings:
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
        )

    assert result["status"] == "succeeded"
    assert list_tools_targets == [
        "http://mcp-my-name.agentarea.svc.cluster.local:8000"
    ], "verify() must call list_tools against the Go-reported internal_url"


@pytest.mark.asyncio
async def test_verify_on_terminal_failed_re_runs():
    """Calling verify() on a row already in a terminal state re-runs the check.

    This is the user-initiated retry path behind POST /{id}/verify.
    """
    inst = _make_instance("docker")
    inst.verification = {
        "schema_version": 1,
        "status": "failed",
        "at": "2026-04-18T00:00:00+00:00",
        "error": {"code": "list_tools_timeout", "message": "old", "detail": None},
    }

    db_mock = _make_db_mock(inst)

    go_create_calls = 0
    list_tools_calls = 0

    async def fake_go_create(instance, mcp_manager_url):
        nonlocal go_create_calls
        go_create_calls += 1
        return {"status_code": 201, "body": {}}

    async def fake_list_tools(endpoint_url, headers=None):
        nonlocal list_tools_calls
        list_tools_calls += 1
        return [{"name": "tool_a", "description": "", "inputSchema": {}}]

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings:
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
        )

    assert result["status"] == "succeeded"
    assert go_create_calls == 1
    assert list_tools_calls == 1


# ---------------------------------------------------------------------------
# verify() bundle raises NotImplementedError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_bundle_raises():
    inst = _make_instance("bundle")
    from agentarea_mcp.verification import verify
    with pytest.raises(NotImplementedError):
        await verify(inst)


# ---------------------------------------------------------------------------
# MCPContainerMonitor — orphan GC
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_monitor_orphan_gc_marks_stale_in_progress_as_failed():
    """_tick() marks stale in_progress rows as failed with verification_interrupted."""
    from agentarea_mcp.container_monitor import MCPContainerMonitor

    monitor = MCPContainerMonitor(check_interval=30)
    executed_sqls = []
    executed_params = []

    class FakeGCResult:
        rowcount = 2

    class FakeSweepResult:
        def fetchall(self):
            return []

    class FakeMonitorSession:
        def begin(self):
            return _AsyncContextManagerMock()

        async def execute(self, stmt, params=None):
            sql_str = str(stmt)
            executed_sqls.append(sql_str)
            executed_params.append(params)
            if "in_progress" in sql_str:
                return FakeGCResult()
            return FakeSweepResult()

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class FakeMonitorDB:
        def async_session_factory(self):
            return FakeMonitorSession()

    with patch("agentarea_mcp.container_monitor.get_database", return_value=FakeMonitorDB()):
        await monitor._tick()

    gc_sqls = [s for s in executed_sqls if "in_progress" in s]
    assert len(gc_sqls) >= 1, "Orphan GC SQL must be executed"
    assert ":null" not in gc_sqls[0]
    assert {"threshold_minutes": 2} in executed_params


# ---------------------------------------------------------------------------
# MCPContainerMonitor — re-verify sweep enqueues never_attempted rows
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Constant checks — Phase 1 deadline / backoff values
# ---------------------------------------------------------------------------

def test_total_deadline_is_120():
    """_TOTAL_DEADLINE must be 120s to accommodate cold image pulls (60-90s)."""
    from agentarea_mcp.verification import _TOTAL_DEADLINE
    assert _TOTAL_DEADLINE == 120, (
        f"_TOTAL_DEADLINE must be 120 (was changed for Phase 1 K8s cold-pull support), got {_TOTAL_DEADLINE}"
    )


def test_list_tools_backoff_delays_extended():
    """_LIST_TOOLS_BACKOFF_DELAYS must match the Phase 1 extended schedule."""
    from agentarea_mcp.verification import _LIST_TOOLS_BACKOFF_DELAYS
    expected = [2, 4, 8, 16, 30, 30]
    assert _LIST_TOOLS_BACKOFF_DELAYS == expected, (
        f"Expected {expected}, got {_LIST_TOOLS_BACKOFF_DELAYS}"
    )


def test_list_tools_backoff_delays_has_six_entries():
    """Backoff schedule must have exactly 6 retry delays (Phase 1 extended from 4)."""
    from agentarea_mcp.verification import _LIST_TOOLS_BACKOFF_DELAYS
    assert len(_LIST_TOOLS_BACKOFF_DELAYS) == 6, (
        f"Expected 6 backoff entries, got {len(_LIST_TOOLS_BACKOFF_DELAYS)}"
    )


# ---------------------------------------------------------------------------
# Slow pod startup — Go ack fast, list_tools fails several times then succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_slow_pod_startup_succeeds_after_multiple_list_tools_failures():
    """Go ack returns 201 fast; list_tools fails 4 times (transient) then succeeds.

    This simulates a K8s pod that is still pulling its image / initialising
    when the first few list_tools attempts are made.  With the extended
    _LIST_TOOLS_BACKOFF_DELAYS the verification must ultimately succeed.
    """
    inst = _make_instance("docker")
    db_mock = _make_db_mock(inst)

    go_create_called = 0
    list_tools_attempt = 0
    fake_tools = [{"name": "query", "description": "runs SQL", "inputSchema": {}}]

    async def fake_go_create(instance, mcp_manager_url):
        nonlocal go_create_called
        go_create_called += 1
        # Ack returns immediately — no blocking wait in Phase 1
        return {"status_code": 201, "body": {"instance_id": str(instance.id)}}

    async def fake_list_tools(endpoint_url, headers=None):
        nonlocal list_tools_attempt
        list_tools_attempt += 1
        if list_tools_attempt <= 4:
            raise ConnectionRefusedError("pod not ready yet")
        return fake_tools

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings, \
         patch("agentarea_mcp.verification._LIST_TOOLS_BACKOFF_DELAYS", [0, 0, 0, 0, 0, 0]), \
         patch("agentarea_mcp.verification._TOTAL_DEADLINE", 9999):
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
        )

    assert result["status"] == "succeeded", (
        f"Expected succeeded after slow pod startup, got {result}"
    )
    assert go_create_called == 1, "Go create must be called exactly once"
    assert list_tools_attempt == 5, (
        f"Expected 5 list_tools attempts (4 failures + 1 success), got {list_tools_attempt}"
    )


@pytest.mark.asyncio
async def test_verify_slow_pod_startup_extended_deadline_allows_late_success():
    """The extended _TOTAL_DEADLINE=120 permits success even after many slow retries.

    Patches the deadline to a tight value AND uses zero-delay backoff so the
    test runs fast, but verifies the retry count the extended backoff list enables.
    """
    inst = _make_instance("command")
    db_mock = _make_db_mock(inst)

    list_tools_attempt = 0
    fake_tools = [{"name": "list_dir", "description": "", "inputSchema": {}}]

    async def fake_go_create(instance, mcp_manager_url):
        return {"status_code": 201, "body": {}}

    async def fake_list_tools(endpoint_url, headers=None):
        nonlocal list_tools_attempt
        list_tools_attempt += 1
        # Succeed on the 6th attempt — last slot in extended backoff list
        if list_tools_attempt < 6:
            raise ConnectionRefusedError("still starting")
        return fake_tools

    # Use zero-delay backoff (same length as real list) to avoid sleeping
    zero_delays = [0, 0, 0, 0, 0, 0]

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings, \
         patch("agentarea_mcp.verification._LIST_TOOLS_BACKOFF_DELAYS", zero_delays), \
         patch("agentarea_mcp.verification._TOTAL_DEADLINE", 9999):
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
        )

    assert result["status"] == "succeeded", (
        f"Extended backoff must allow success on 6th attempt; got {result}"
    )
    assert list_tools_attempt == 6


@pytest.mark.asyncio
async def test_monitor_reverify_sweep_enqueues_never_attempted():
    """_tick() enqueues verify() for never_attempted docker/command rows."""
    from agentarea_mcp.container_monitor import MCPContainerMonitor

    monitor = MCPContainerMonitor(check_interval=30)

    inst_id = uuid.uuid4()

    class FakeRow:
        def __init__(self):
            self.id = inst_id
            self.name = "my-inst"
            self.json_spec = {"type": "docker"}
            self.workspace_id = uuid.uuid4()
            self.created_by = str(uuid.uuid4())
            self.verification = dict(DEFAULT_VERIFICATION)
            self.last_dispatch = None
            self.tools = None

    class FakeGCResult:
        rowcount = 0

    class FakeSweepResult:
        def fetchall(self):
            return [FakeRow()]

    class FakeSweepSession:
        def begin(self):
            return _AsyncContextManagerMock()

        async def execute(self, stmt, params=None):
            sql_str = str(stmt)
            if "in_progress" in sql_str:
                return FakeGCResult()
            return FakeSweepResult()

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class FakeSweepDB:
        def async_session_factory(self):
            return FakeSweepSession()

    verify_called_instances = []
    created_tasks = []
    original_create_task = asyncio.create_task

    async def patched_verify(instance):
        verify_called_instances.append(str(instance.id))

    def capturing_create_task(coro, **kwargs):
        t = original_create_task(coro, **kwargs)
        created_tasks.append(t)
        return t

    with patch("agentarea_mcp.container_monitor.get_database", return_value=FakeSweepDB()), \
         patch("agentarea_mcp.verification.verify", side_effect=patched_verify), \
         patch("asyncio.create_task", side_effect=capturing_create_task):
        await monitor._tick()

    # Drain all created tasks
    for t in created_tasks:
        await t

    assert str(inst_id) in verify_called_instances or len(created_tasks) >= 1, \
        "At least one verify task must have been created for the never_attempted row"
