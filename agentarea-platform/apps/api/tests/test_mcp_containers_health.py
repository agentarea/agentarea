"""The MCP container-health endpoint must only speak about its own workspace.

The manager exposes a route that answers for every workload on the host, and
proxying it straight through would have handed one workspace the service names and
container ids of another. These tests pin the two properties that keep that from
happening again: the endpoint asks only about ids the workspace-scoped service
returned, and an unhealthy or unknown workload is reported rather than turned into
a failure of the whole request.
"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from agentarea_api.api.v1 import mcp_server_instances as module


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class _Client:
    """Records every URL asked about and answers from a fixed table."""

    def __init__(self, answers, asked):
        self._answers = answers
        self._asked = asked

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        self._asked.append(url)
        answer = self._answers.get(url)
        if answer is None:
            return _Response(404, text="unknown instance")
        if isinstance(answer, Exception):
            raise answer
        return answer


def _service(instances):
    async def _list():
        return instances

    return SimpleNamespace(list=_list)


def _context():
    return SimpleNamespace(user_id="u", workspace_id="w")


def _health_url(instance_id):
    return f"http://manager/instances/{instance_id}/health"


def _install(monkeypatch, answers, asked):
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(mcp=SimpleNamespace(MCP_MANAGER_URL="http://manager")),
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client(answers, asked))


def test_only_workspace_instances_are_asked_about(monkeypatch):
    mine, theirs = uuid4(), uuid4()
    asked = []
    answers = {_health_url(mine): _Response(200, {"healthy": True, "status": "running"})}
    _install(monkeypatch, answers, asked)

    result = asyncio.run(
        module.get_containers_health(
            user_context=_context(),
            service=_service([SimpleNamespace(id=mine, name="mine")]),
        )
    )

    assert asked == [_health_url(mine)]
    assert str(theirs) not in str(result)
    assert result["total"] == 1
    assert result["healthy"] == 1
    assert result["instances"][0]["instance_id"] == str(mine)


def test_unhealthy_workload_is_reported_not_raised(monkeypatch):
    iid = uuid4()
    asked = []
    answers = {_health_url(iid): _Response(503, {"healthy": False, "status": "exited"})}
    _install(monkeypatch, answers, asked)

    result = asyncio.run(
        module.get_containers_health(
            user_context=_context(),
            service=_service([SimpleNamespace(id=iid, name="sick")]),
        )
    )

    row = result["instances"][0]
    assert row["healthy"] is False
    assert row["status"] == "exited"
    assert result["healthy"] == 0
    assert result["total"] == 1


def test_unknown_and_unreachable_are_distinguished(monkeypatch):
    known, gone = uuid4(), uuid4()
    asked = []
    answers = {_health_url(known): httpx.RequestError("connection refused")}
    _install(monkeypatch, answers, asked)

    result = asyncio.run(
        module.get_containers_health(
            user_context=_context(),
            service=_service(
                [SimpleNamespace(id=known, name="a"), SimpleNamespace(id=gone, name="b")]
            ),
        )
    )

    by_id = {row["instance_id"]: row["status"] for row in result["instances"]}
    assert by_id[str(known)] == "manager_unreachable"
    assert by_id[str(gone)] == "not_running"
    assert result["healthy"] == 0
    assert result["total"] == 2


def test_no_instances_is_an_empty_report(monkeypatch):
    asked = []
    _install(monkeypatch, {}, asked)

    result = asyncio.run(
        module.get_containers_health(user_context=_context(), service=_service([]))
    )

    assert result == {"instances": [], "total": 0, "healthy": 0}
    assert asked == []


@pytest.mark.parametrize("status", [500, 502])
def test_manager_error_status_becomes_a_per_instance_error(monkeypatch, status):
    iid = uuid4()
    asked = []
    answers = {_health_url(iid): _Response(status, text="boom")}
    _install(monkeypatch, answers, asked)

    result = asyncio.run(
        module.get_containers_health(
            user_context=_context(),
            service=_service([SimpleNamespace(id=iid, name="x")]),
        )
    )

    assert result["instances"][0]["status"] == "error"
