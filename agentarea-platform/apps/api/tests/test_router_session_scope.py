"""A request sees one database session, whichever alias a route declares it with.

FastAPI caches a dependency per (callable, scope). The service dependencies take
`get_db_session` function-scoped, so a router alias left request-scoped opened a
second session in the same request: the handler read through one transaction
what the service had written, uncommitted, through the other (POST /agents
answered with approval flags it had just stored as unset).
"""

import importlib
import pkgutil
from typing import Any

import pytest
from agentarea_api.api import v1
from agentarea_api.api.deps.services import DatabaseSessionDep as ServiceSessionDep
from agentarea_common.config.database import get_db_session
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _router_session_aliases() -> list[tuple[str, Any]]:
    aliases = []
    for module_info in pkgutil.iter_modules(v1.__path__):
        module = importlib.import_module(f"{v1.__name__}.{module_info.name}")
        alias = getattr(module, "DatabaseSessionDep", None)
        if alias is not None:
            aliases.append((module_info.name, alias))
    return aliases


@pytest.mark.parametrize(("module", "alias"), _router_session_aliases())
def test_route_and_service_share_one_session(module: str, alias: Any) -> None:
    opened: list[object] = []

    async def counting_session():
        session = object()
        opened.append(session)
        yield session

    app = FastAPI()
    app.dependency_overrides[get_db_session] = counting_session

    @app.get("/probe")
    async def probe(route_session: alias, service_session: ServiceSessionDep) -> dict:
        return {"same": route_session is service_session}

    response = TestClient(app).get("/probe")

    assert response.json() == {"same": True}, f"{module} opens a second session"
    assert len(opened) == 1
