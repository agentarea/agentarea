"""Tests for agentarea_mcp.verification.verify() and MCPContainerMonitor."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from agentarea_mcp.domain.verification_types import DEFAULT_VERIFICATION


# ---------------------------------------------------------------------------
# _in_progress_is_stale — wedged-verifying self-heal
# ---------------------------------------------------------------------------


def test_in_progress_stale_detection():
    from agentarea_mcp.verification import _in_progress_is_stale

    now = datetime.now(UTC)
    # Fresh in_progress → live, must not be treated as stale.
    assert _in_progress_is_stale({"status": "in_progress", "at": now.isoformat()}) is False
    # Older than the safety deadline (600s) → abandoned → stale.
    old = (now - timedelta(seconds=700)).isoformat()
    assert _in_progress_is_stale({"status": "in_progress", "at": old}) is True
    # Missing / unparseable timestamps are treated as stale (can't trust them live).
    assert _in_progress_is_stale({"status": "in_progress"}) is True
    assert _in_progress_is_stale({"status": "in_progress", "at": "not-a-date"}) is True
    # Naive timestamp is assumed UTC.
    naive_old = (now - timedelta(seconds=700)).replace(tzinfo=None).isoformat()
    assert _in_progress_is_stale({"at": naive_old}) is True

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
        self.server_spec_id = "test-spec-id"
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
            self._exec_call += 1
            if self._exec_call == 2:
                server = MagicMock()
                server.id = "test-spec-id"
                server.remote_url = (
                    instance.json_spec.get("endpoint_url")
                    if instance.json_spec.get("type") == "url"
                    else None
                )
                server.cmd = None
                server.docker_image_url = "test-image:latest"
                server.json_spec = dict(instance.json_spec or {})
                server.json_spec.setdefault("image", "test-image:latest")
                server.env_schema = []
                result.scalar_one_or_none.return_value = server
            else:
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

    # Container stays alive-but-not-ready and list_tools never answers: the loop
    # exits via the safety cap, then enriches the error from the health call.
    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings, \
         patch("agentarea_mcp.verification._LIST_TOOLS_RETRY_DELAY", 0), \
         patch("agentarea_mcp.verification._SAFETY_DEADLINE", 0.05):
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
    """A genuinely in-flight (recent) in_progress must not be re-run."""
    inst = _make_instance("docker")
    inst.verification = {
        "schema_version": 1,
        "status": "in_progress",
        "at": datetime.now(UTC).isoformat(),  # fresh → live
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
async def test_verify_stale_in_progress_reruns():
    """A stale in_progress (interrupted previous run) must self-heal by re-running."""
    inst = _make_instance("docker")
    inst.verification = {
        "schema_version": 1,
        "status": "in_progress",
        "at": (datetime.now(UTC) - timedelta(seconds=700)).isoformat(),  # abandoned
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
        result = await verify(inst, _list_tools_fn=fake_list_tools, _go_create_fn=fake_go_create)

    assert result["status"] == "succeeded"
    assert go_create_calls == 1


@pytest.mark.asyncio
async def test_verify_force_reruns_even_when_fresh_in_progress():
    """force=True (user clicked Verify) re-runs even a recent in_progress."""
    inst = _make_instance("docker")
    inst.verification = {
        "schema_version": 1,
        "status": "in_progress",
        "at": datetime.now(UTC).isoformat(),  # fresh, but user forced
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
            inst, force=True, _list_tools_fn=fake_list_tools, _go_create_fn=fake_go_create
        )

    assert result["status"] == "succeeded"
    assert go_create_calls == 1


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
# verify() merges extra_headers into list_tools call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_passes_extra_headers_to_list_tools():
    """When verify() is called with extra_headers (e.g. OAuth Bearer), they
    must be merged with json_spec headers and passed to list_tools."""
    inst = _make_instance("url")
    inst.json_spec = {
        "type": "url",
        "endpoint_url": "https://mcp.notion.com/sse",
        "headers": {"X-Custom": "value"},
    }
    db_mock = _make_db_mock(inst)

    captured_headers: list[dict] = []

    async def fake_list_tools(endpoint_url, headers=None):
        captured_headers.append(headers or {})
        return [{"name": "search", "description": "", "inputSchema": {}}]

    async def fake_go_create(instance, mcp_manager_url):
        return {"status_code": 201, "body": {}}

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings:
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            extra_headers={"Authorization": "Bearer abc123"},
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
        )

    assert result["status"] == "succeeded"
    assert captured_headers, "list_tools must be called"
    headers = captured_headers[0]
    assert headers.get("Authorization") == "Bearer abc123"
    assert headers.get("X-Custom") == "value"


# ---------------------------------------------------------------------------
# _list_tools URL transport selection — preserves explicit /sse and /mcp
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tools_with_explicit_sse_url_does_not_double_sse():
    """For URLs ending in /sse, _list_tools must use SSE transport directly,
    NOT munge to /mcp first and then strip-and-append /sse (which produced /sse/sse)."""
    from agentarea_mcp import verification as ver

    sse_targets: list[str] = []
    streamable_called = False

    class _FakeStream:
        async def __aenter__(self):
            return (object(), object(), object())

        async def __aexit__(self, *args):
            return False

    class _FakeSSEStream:
        def __init__(self, url):
            sse_targets.append(url)

        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def __init__(self, *_args, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def initialize(self):
            pass

        async def list_tools(self):
            r = MagicMock()
            r.tools = []
            return r

    def fake_streamable(url, **kw):
        nonlocal streamable_called
        streamable_called = True
        return _FakeStream()

    def fake_sse(url, **kw):
        return _FakeSSEStream(url)

    import sys

    fake_streamable_mod = MagicMock()
    fake_streamable_mod.streamablehttp_client = fake_streamable
    fake_sse_mod = MagicMock()
    fake_sse_mod.sse_client = fake_sse
    fake_mcp_mod = MagicMock()
    fake_mcp_mod.ClientSession = _FakeSession

    with patch.dict(sys.modules, {
        "mcp": fake_mcp_mod,
        "mcp.client.streamable_http": fake_streamable_mod,
        "mcp.client.sse": fake_sse_mod,
    }):
        await ver._list_tools("https://mcp.notion.com/sse")

    assert sse_targets == ["https://mcp.notion.com/sse"], (
        f"Explicit /sse URL must be passed unchanged to sse_client; got {sse_targets!r}"
    )
    assert not streamable_called, (
        "Streamable HTTP must NOT be tried first when URL is explicitly /sse "
        "(prevents transforming to /sse/mcp -> /sse/sse)"
    )


@pytest.mark.asyncio
async def test_list_tools_with_explicit_mcp_url_uses_streamable_directly():
    """URLs ending in /mcp must go straight to streamable-http, not be re-suffixed."""
    from agentarea_mcp import verification as ver

    streamable_targets: list[str] = []

    class _FakeStream:
        def __init__(self, url):
            streamable_targets.append(url)

        async def __aenter__(self):
            return (object(), object(), object())

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def initialize(self):
            pass

        async def list_tools(self):
            r = MagicMock()
            r.tools = []
            return r

    def fake_streamable(url, **kw):
        return _FakeStream(url)

    def fake_sse(url, **kw):
        raise AssertionError("SSE should not be reached when streamable succeeds")

    import sys

    fake_streamable_mod = MagicMock()
    fake_streamable_mod.streamablehttp_client = fake_streamable
    fake_sse_mod = MagicMock()
    fake_sse_mod.sse_client = fake_sse
    fake_mcp_mod = MagicMock()
    fake_mcp_mod.ClientSession = _FakeSession

    with patch.dict(sys.modules, {
        "mcp": fake_mcp_mod,
        "mcp.client.streamable_http": fake_streamable_mod,
        "mcp.client.sse": fake_sse_mod,
    }):
        await ver._list_tools("https://example.com/mcp")

    assert streamable_targets == ["https://example.com/mcp"]


@pytest.mark.asyncio
async def test_list_tools_with_unsuffixed_url_tries_bare_then_mcp_then_sse():
    """For bare URLs, try the URL as-given first, then /mcp, then fall back to /sse."""
    from agentarea_mcp import verification as ver

    streamable_targets: list[str] = []
    sse_targets: list[str] = []

    class _FailStream:
        def __init__(self, url):
            streamable_targets.append(url)

        async def __aenter__(self):
            raise ConnectionError("streamable not supported")

        async def __aexit__(self, *args):
            return False

    class _FakeSSEStream:
        def __init__(self, url):
            sse_targets.append(url)

        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def initialize(self):
            pass

        async def list_tools(self):
            r = MagicMock()
            r.tools = []
            return r

    def fake_streamable(url, **kw):
        return _FailStream(url)

    def fake_sse(url, **kw):
        return _FakeSSEStream(url)

    import sys

    fake_streamable_mod = MagicMock()
    fake_streamable_mod.streamablehttp_client = fake_streamable
    fake_sse_mod = MagicMock()
    fake_sse_mod.sse_client = fake_sse
    fake_mcp_mod = MagicMock()
    fake_mcp_mod.ClientSession = _FakeSession

    with patch.dict(sys.modules, {
        "mcp": fake_mcp_mod,
        "mcp.client.streamable_http": fake_streamable_mod,
        "mcp.client.sse": fake_sse_mod,
    }):
        await ver._list_tools("https://example.com")

    assert streamable_targets == ["https://example.com", "https://example.com/mcp"]
    assert sse_targets == ["https://example.com/sse"]


def test_declared_remote_transport_reads_remotes_type():
    from agentarea_mcp.verification import declared_remote_transport

    spec = {"remotes": [{"type": "streamable-http", "url": "https://mcp.vercel.com"}]}
    assert declared_remote_transport(spec) == "streamable-http"
    assert declared_remote_transport({"remotes": [{"type": "sse", "url": "x"}]}) == "sse"


def test_declared_remote_transport_none_when_absent():
    from agentarea_mcp.verification import declared_remote_transport

    assert declared_remote_transport(None) is None
    assert declared_remote_transport({}) is None
    assert declared_remote_transport({"remotes": []}) is None
    assert declared_remote_transport({"remotes": [{"url": "x"}]}) is None


def test_transport_candidates_declared_transport_is_authoritative():
    """A declared transport is honored exactly — no probing, no cross fallback."""
    from agentarea_mcp.verification import mcp_transport_candidates

    # streamable-http at the root, no SSE fallback
    assert mcp_transport_candidates("https://mcp.vercel.com", "streamable-http") == (
        ["https://mcp.vercel.com"],
        None,
    )
    # underscore variant tolerated
    assert mcp_transport_candidates("https://x", "streamable_http") == (["https://x"], None)
    # sse declared
    assert mcp_transport_candidates("https://x", "sse") == ([], "https://x")
    # unknown/garbage transport falls through to suffix heuristics
    assert mcp_transport_candidates("https://x", "bogus") == (
        ["https://x", "https://x/mcp"],
        "https://x/sse",
    )


@pytest.mark.asyncio
async def test_list_tools_declared_streamable_does_not_fall_back_to_sse():
    """When the spec declares streamable-http and it fails, surface the real error
    instead of silently probing /sse (which would 404 on servers like Vercel)."""
    from agentarea_mcp import verification as ver

    class _FailStream:
        def __init__(self, url):
            pass

        async def __aenter__(self):
            raise ConnectionError("boom")

        async def __aexit__(self, *args):
            return False

    def fake_streamable(url, **kw):
        return _FailStream(url)

    def fake_sse(url, **kw):
        raise AssertionError("SSE must not be attempted for a declared streamable-http server")

    import sys

    fake_streamable_mod = MagicMock()
    fake_streamable_mod.streamablehttp_client = fake_streamable
    fake_sse_mod = MagicMock()
    fake_sse_mod.sse_client = fake_sse
    fake_mcp_mod = MagicMock()
    fake_mcp_mod.ClientSession = MagicMock()

    with patch.dict(sys.modules, {
        "mcp": fake_mcp_mod,
        "mcp.client.streamable_http": fake_streamable_mod,
        "mcp.client.sse": fake_sse_mod,
    }):
        with pytest.raises(ConnectionError, match="boom"):
            await ver._list_tools("https://mcp.vercel.com", None, "streamable-http")


@pytest.mark.asyncio
async def test_list_tools_bare_url_uses_streamable_at_root():
    """Regression (Vercel): a bare URL whose server serves streamable-HTTP at the
    root must connect to the URL as-given — not be re-suffixed to /mcp or /sse.

    https://mcp.vercel.com serves streamable-HTTP at the root; appending /mcp or
    /sse 404s. The 404-on-/sse verification failure came from never trying the
    provided URL directly.
    """
    from agentarea_mcp import verification as ver

    streamable_targets: list[str] = []

    class _FakeStream:
        def __init__(self, url):
            streamable_targets.append(url)

        async def __aenter__(self):
            return (object(), object(), object())

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def initialize(self):
            pass

        async def list_tools(self):
            r = MagicMock()
            r.tools = []
            return r

    def fake_streamable(url, **kw):
        return _FakeStream(url)

    def fake_sse(url, **kw):
        raise AssertionError("SSE must not be reached when the bare URL succeeds")

    import sys

    fake_streamable_mod = MagicMock()
    fake_streamable_mod.streamablehttp_client = fake_streamable
    fake_sse_mod = MagicMock()
    fake_sse_mod.sse_client = fake_sse
    fake_mcp_mod = MagicMock()
    fake_mcp_mod.ClientSession = _FakeSession

    with patch.dict(sys.modules, {
        "mcp": fake_mcp_mod,
        "mcp.client.streamable_http": fake_streamable_mod,
        "mcp.client.sse": fake_sse_mod,
    }):
        await ver._list_tools("https://mcp.vercel.com")

    assert streamable_targets == ["https://mcp.vercel.com"]


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
    from agentarea_mcp.container_monitor import _ORPHAN_THRESHOLD_MINUTES
    assert {"threshold_minutes": _ORPHAN_THRESHOLD_MINUTES} in executed_params
    # The orphan backstop must outlast the longest legit verify() so a healthy
    # but slow cold install is never reaped mid-flight.
    from agentarea_mcp.verification import _SAFETY_DEADLINE
    assert _ORPHAN_THRESHOLD_MINUTES * 60 > _SAFETY_DEADLINE


# ---------------------------------------------------------------------------
# MCPContainerMonitor — re-verify sweep enqueues never_attempted rows
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Constant checks — liveness-driven verification
# ---------------------------------------------------------------------------

def test_safety_deadline_is_generous():
    """Verification is liveness-driven: it keeps polling while the container is
    alive and only treats a runtime-reported death as terminal. The wall-clock
    cap is just a backstop and must be generous enough for cold `uvx`/`npx`
    installs (which can take minutes)."""
    from agentarea_mcp.verification import _SAFETY_DEADLINE
    assert _SAFETY_DEADLINE >= 300, (
        f"_SAFETY_DEADLINE must be >= 300s to allow cold command/docker installs, got {_SAFETY_DEADLINE}"
    )


def test_list_tools_retry_delay_is_small():
    """Between attempts we poll at a small steady interval while provisioning."""
    from agentarea_mcp.verification import _LIST_TOOLS_RETRY_DELAY
    assert 0 < _LIST_TOOLS_RETRY_DELAY <= 10, (
        f"_LIST_TOOLS_RETRY_DELAY must be a small steady interval, got {_LIST_TOOLS_RETRY_DELAY}"
    )


# ---------------------------------------------------------------------------
# Slow pod startup — Go ack fast, list_tools fails several times then succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_slow_pod_startup_succeeds_after_multiple_list_tools_failures():
    """Go ack returns 201 fast; list_tools fails 4 times (transient) then succeeds.

    This simulates a K8s pod that is still pulling its image / initialising
    when the first few list_tools attempts are made.  As long as the container
    is alive (health != error) verification keeps polling and must ultimately
    succeed.
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

    async def fake_health(instance_id, mcp_manager_url):
        # Alive but not ready yet — never terminal.
        return {"state": "starting", "healthy": False}

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings, \
         patch("agentarea_mcp.verification._LIST_TOOLS_RETRY_DELAY", 0):
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
            _go_health_fn=fake_health,
        )

    assert result["status"] == "succeeded", (
        f"Expected succeeded after slow pod startup, got {result}"
    )
    assert go_create_called == 1, "Go create must be called exactly once"
    assert list_tools_attempt == 5, (
        f"Expected 5 list_tools attempts (4 failures + 1 success), got {list_tools_attempt}"
    )


@pytest.mark.asyncio
async def test_verify_slow_pod_startup_many_retries_allows_late_success():
    """A command server that only becomes ready after many slow retries still
    succeeds: while the container is alive, verification keeps polling.

    Uses zero retry delay so the test runs fast.
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
        # Still installing for the first 9 attempts, ready on the 10th.
        if list_tools_attempt < 10:
            raise ConnectionRefusedError("still starting")
        return fake_tools

    async def fake_health(instance_id, mcp_manager_url):
        # Alive but not ready — never terminal, so polling continues.
        return {"state": "starting", "healthy": False}

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings, \
         patch("agentarea_mcp.verification._LIST_TOOLS_RETRY_DELAY", 0):
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
            _go_health_fn=fake_health,
        )

    assert result["status"] == "succeeded", (
        f"Liveness-driven retries must allow late success; got {result}"
    )
    assert list_tools_attempt == 10


@pytest.mark.asyncio
async def test_verify_fails_fast_when_container_dies_mid_provision():
    """If the runtime reports the container entered an error state while we are
    still polling, verify() fails immediately (no waiting out the safety cap)."""
    inst = _make_instance("command")
    db_mock = _make_db_mock(inst)

    list_tools_attempt = 0
    health_attempt = 0

    async def fake_go_create(instance, mcp_manager_url):
        return {"status_code": 201, "body": {}}

    async def fake_list_tools(endpoint_url, headers=None):
        nonlocal list_tools_attempt
        list_tools_attempt += 1
        raise ConnectionRefusedError("still starting")

    async def fake_health(instance_id, mcp_manager_url):
        nonlocal health_attempt
        health_attempt += 1
        # Alive for the first poll, then the container dies.
        if health_attempt >= 2:
            return {"state": "error", "healthy": False, "details": "child process exited"}
        return {"state": "starting", "healthy": False}

    with patch("agentarea_mcp.verification.get_database", return_value=db_mock), \
         patch("agentarea_mcp.verification.get_settings") as mock_settings, \
         patch("agentarea_mcp.verification._LIST_TOOLS_RETRY_DELAY", 0), \
         patch("agentarea_mcp.verification._SAFETY_DEADLINE", 9999):
        mock_settings.return_value.mcp.MCP_MANAGER_URL = "http://fake-go:7999"

        from agentarea_mcp.verification import verify
        result = await verify(
            inst,
            _list_tools_fn=fake_list_tools,
            _go_create_fn=fake_go_create,
            _go_health_fn=fake_health,
        )

    assert result["status"] == "failed"
    assert result["error"]["code"] == "container_failed"
    # Failed fast on the 2nd health poll — did not spin out the safety cap.
    assert health_attempt == 2


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
