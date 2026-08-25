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


def _route():
    return next(
        route
        for route in module.router.routes
        if getattr(route, "path", None) == "/mcp-server-instances/health/containers"
    )


def test_endpoint_declares_its_response_shape():
    """An undeclared shape is invisible to the spec, and therefore to clients.

    This endpoint answered a bare dict, so the exported OpenAPI carried no
    response schema and the generated clients typed it as unknown. The webapp
    filled that gap with a hand-written type, kept reading a key the endpoint had
    stopped sending, and crashed on it. The contract is declared so the next
    change to it moves the spec and the clients with it.
    """
    assert _route().response_model is module.MCPContainersHealthResponse


def test_declared_shape_carries_every_reported_field():
    row = module.MCPInstanceHealthResponse.model_validate(
        {
            "instance_id": "6f1c1f52-0d6d-4a1e-8a5f-0f6f7a4f9a11",
            "name": "telegram",
            "healthy": False,
            "status": "not_running",
        }
    )

    assert row.model_dump() == {
        "instance_id": "6f1c1f52-0d6d-4a1e-8a5f-0f6f7a4f9a11",
        "name": "telegram",
        "healthy": False,
        "status": "not_running",
    }


def test_the_managers_own_health_body_is_not_passed_through(monkeypatch):
    """The verdict is the answer; the data plane's internals are not.

    The manager reports container ids, images, ports and the gateway path it
    serves a workload on. Echoing that to a caller would turn a health check into
    a way to enumerate the data plane, so the row must carry none of it.
    """
    iid = uuid4()
    answers = {
        _health_url(iid): _Response(
            200,
            {
                "healthy": True,
                "status": "running",
                "container_id": "9f2c1e",
                "container_image": "ghcr.io/example/mcp:1",
                "proxy_url": "/mcp/telegram",
            },
        )
    }
    _install(monkeypatch, answers, [])

    result = asyncio.run(
        module.get_containers_health(
            user_context=_context(),
            service=_service([SimpleNamespace(id=iid, name="telegram")]),
        )
    )

    assert set(result["instances"][0]) == {"instance_id", "name", "healthy", "status"}
    for leaked in ("9f2c1e", "ghcr.io/example/mcp:1", "/mcp/telegram"):
        assert leaked not in str(result)


def test_every_answer_the_endpoint_can_give_validates_against_the_contract(monkeypatch):
    """Each branch of read_one must survive its own response_model."""
    healthy, sick, unreachable, missing = uuid4(), uuid4(), uuid4(), uuid4()
    answers = {
        _health_url(healthy): _Response(200, {"healthy": True, "status": "running"}),
        _health_url(sick): _Response(503, {"healthy": False, "status": "exited"}),
        _health_url(unreachable): httpx.RequestError("connection refused"),
    }
    _install(monkeypatch, answers, [])

    result = asyncio.run(
        module.get_containers_health(
            user_context=_context(),
            service=_service(
                [
                    SimpleNamespace(id=iid, name=str(iid))
                    for iid in (healthy, sick, unreachable, missing)
                ]
            ),
        )
    )

    validated = module.MCPContainersHealthResponse.model_validate(result)
    assert {row.status for row in validated.instances} == {
        "running",
        "exited",
        "manager_unreachable",
        "not_running",
    }
    assert validated.total == 4
    assert validated.healthy == 1
