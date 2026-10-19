"""In-memory DB fixtures for registry repository tests.

Mirrors tests/integration/repositories/conftest.py: SQLite in-memory on a
StaticPool so the whole test shares one connection. Browse queries are kept
dialect-agnostic (plain columns, no JSONB operators) precisely so they can be
covered here rather than only against a live Postgres.
"""

import pytest
import pytest_asyncio
from agentarea_common.base.models import BaseModel
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry, RegistryItem  # noqa: F401  (registers tables)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool


# The catalog's spec/tags columns are declared JSONB (Postgres in production).
# SQLite has no such type, so DDL for registry_items cannot compile without a
# rendering for it. Nothing under test reads through a JSON operator -- browse
# filters and sorts on plain columns -- so plain JSON storage is enough.
@compiles(JSONB, "sqlite")
def _render_jsonb_as_json_on_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest.fixture(autouse=True)
def _no_source_etag(monkeypatch):
    # Sources in these tests are fakes behind _fetch_source; a HEAD request
    # would go to the network. No ETag means every sync reads its source.
    monkeypatch.setattr(RegistryService, "_source_etag", staticmethod(lambda _url: None))


# Names the source-safety tests resolve; an address literal is itself, the
# test database's host resolves for real, and any other name is a public host.
_TEST_HOSTS = {"metadata.example": "169.254.169.254", "openfga": "10.43.0.12"}


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    import ipaddress
    import socket

    real = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if host == "localhost":
            return real(host, port, *args, **kwargs)
        try:
            address = str(ipaddress.ip_address(host))
        except ValueError:
            address = _TEST_HOSTS.get(host, "93.184.216.34")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
