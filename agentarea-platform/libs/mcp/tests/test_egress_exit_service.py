"""The rules of changing an egress exit that instances leave through."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_mcp.application import egress_exit_service as module
from agentarea_mcp.application.egress_exit_service import (
    EgressExitInUseError,
    EgressExitService,
    EgressExitValidationError,
    PlatformEgressExitError,
)
from agentarea_mcp.domain.transport import MCPTransport
from agentarea_mcp.schemas.egress_exit_dto import EgressExitUpdate

CALLER = UserContext(user_id="member", workspace_id="ws-1")


class _Session:
    def __init__(self) -> None:
        self.added: list = []
        self.executed: list = []

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        pass

    async def execute(self, statement):
        self.executed.append(statement)

    async def commit(self) -> None:
        pass


def _row(**fields):
    defaults = {
        "id": uuid4(),
        "name": "office",
        "upstream_url": "https://proxy.example.com:443",
        "username": None,
        "password_secret_id": None,
        "allow_plaintext_credentials": False,
        "managed_by": None,
        "description": None,
    }
    row = SimpleNamespace(**{**defaults, **fields})
    row.is_platform = row.managed_by == "platform"
    return row


class _Exits:
    def __init__(self, session: _Session, row, bound: list) -> None:
        self.session = session
        self.user_context = CALLER
        self.row = row
        self.bound = bound
        self.updated: dict | None = None
        self.deleted = False

    async def get_by_id(self, exit_id):
        return self.row if exit_id == self.row.id else None

    async def get(self, exit_id):
        return await self.get_by_id(exit_id)

    async def bound_instances(self, exit_id):
        return self.bound

    async def update(self, exit_id, **changes):
        self.updated = changes
        for key, value in changes.items():
            setattr(self.row, key, value)
        return self.row

    async def delete(self, exit_id):
        self.deleted = True
        return True


def _service(row, bound=()) -> tuple[EgressExitService, _Exits]:
    session = _Session()
    exits = _Exits(session, row, list(bound))
    factory = SimpleNamespace(
        session=session, user_context=CALLER, create_repository=lambda cls: exits
    )
    return EgressExitService(factory, secret_manager=SimpleNamespace()), exits


def _instance(transport=MCPTransport.DOCKER):
    return SimpleNamespace(id=uuid4(), name=f"mcp-{uuid4().hex[:4]}", transport=transport)


@pytest.fixture
def retired(monkeypatch) -> list[UUID]:
    calls: list[UUID] = []

    async def retire(instance_id):
        calls.append(instance_id)

    monkeypatch.setattr(module, "retire_runtime_before_mutation", retire)
    return calls


async def test_an_exit_instances_leave_through_is_not_deleted_under_them():
    row = _row()
    service, exits = _service(row, bound=[_instance()])

    with pytest.raises(EgressExitInUseError, match="unbind them"):
        await service.delete(row.id)
    assert exits.deleted is False


async def test_a_platform_exit_is_bound_but_never_changed(retired):
    row = _row(managed_by="platform", upstream_url=None)
    service, exits = _service(row)

    with pytest.raises(PlatformEgressExitError):
        await service.update(row.id, EgressExitUpdate(description="mine now"))
    with pytest.raises(PlatformEgressExitError):
        await service.delete(row.id)
    assert exits.updated is None and exits.deleted is False


async def test_a_new_route_restarts_the_running_instances_before_it_is_stored(
    retired, monkeypatch
):
    async def public(url):
        return None

    monkeypatch.setattr(module, "_assert_upstream_public", public)
    docker, url_instance = _instance(), _instance(MCPTransport.URL)
    row = _row()
    service, exits = _service(row, bound=[docker, url_instance])

    await service.update(row.id, EgressExitUpdate(upstream_url="https://other.example.com:443"))

    assert retired == [docker.id]
    assert exits.updated == {"upstream_url": "https://other.example.com:443"}


async def test_a_new_description_restarts_nothing(retired):
    row = _row()
    service, exits = _service(row, bound=[_instance()])

    await service.update(row.id, EgressExitUpdate(description="the office proxy"))

    assert retired == []
    assert exits.updated == {"description": "the office proxy"}


async def test_an_exit_cannot_lose_where_it_leads(retired):
    row = _row()
    service, exits = _service(row)

    with pytest.raises(EgressExitValidationError, match="cannot be cleared"):
        await service.update(row.id, EgressExitUpdate(upstream_url=None))
    assert exits.updated is None


async def test_credentials_added_to_a_plaintext_proxy_are_refused(retired):
    row = _row(upstream_url="http://proxy.example.com:3128")
    service, exits = _service(row)

    with pytest.raises(EgressExitValidationError, match="unencrypted"):
        await service.update(row.id, EgressExitUpdate(username="u"))
    assert exits.updated is None


async def test_a_platform_exit_binds_without_a_grant_and_an_own_one_needs_use(monkeypatch):
    checked: list[tuple[str, str, str]] = []

    async def require_permission(permission, resource_type, resource_id, caller):
        checked.append((permission, resource_type, resource_id))

    monkeypatch.setattr(module, "require_permission", require_permission)

    platform = _row(managed_by="platform", upstream_url=None)
    service, _ = _service(platform)
    assert await service.require_bindable(platform.id) is platform
    assert checked == []

    own = _row()
    service, _ = _service(own)
    assert await service.require_bindable(own.id) is own
    assert checked == [("use", "egress_exit", str(own.id))]
