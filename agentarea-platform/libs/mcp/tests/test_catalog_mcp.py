"""MCP server spec catalog read-path tests (ADR-003).

Built-in MCP server specs live in the registry catalog (``registry_items`` of
``registry_type='mcp_servers'``) and are merged into the spec list read-only.
Unlike agents/skills there is no copy-on-write fork: built-in specs are
reference specs users instantiate via ``mcp_server_instances``. These tests
exercise the repository merge with light fakes, no database.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.infrastructure.catalog_mcp_repository import CatalogMcpItem
from agentarea_mcp.infrastructure.repository import (
    MCPServerRepository,
    _project_catalog_mcp_server,
)

_TS = datetime(2024, 1, 2, 3, 4, 5)


def _item(item_id=None, name="Built-in", version="1", spec=None, tags=None, ts=_TS):
    return CatalogMcpItem(
        id=item_id or str(uuid4()),
        name=name,
        description="desc",
        version=version,
        spec=spec or {"connection_type": "url", "url": "https://x", "env_schema": []},
        tags=tags or ["url"],
        registry_url="https://registry.example.com",
        created_at=ts,
        updated_at=ts,
    )


class FakeCatalogRepo:
    def __init__(self, items=None):
        self._items = items or []

    async def list_items(self):
        return list(self._items)

    async def get_item(self, item_id):
        return next((i for i in self._items if i.id == item_id), None)


def _repo(catalog):
    uc = UserContext(user_id="u1", workspace_id="w1")
    repo = MCPServerRepository(session=object(), user_context=uc)
    repo._get_catalog_repository = lambda: catalog
    return repo


def test_project_marks_read_only_with_provenance():
    item = _item(spec={"connection_type": "url", "url": "https://api/mcp", "env_schema": []})
    server = _project_catalog_mcp_server(item)
    assert str(server.id) == item.id
    # registry_item_id is stored as a real uuid; the fixture id is its string form
    assert str(server.registry_item_id) == item.id
    assert server.is_catalog is True
    assert server.remote_url == "https://api/mcp"
    assert server.registry_url == "https://registry.example.com"


def test_project_carries_registry_item_timestamps():
    """The transient projection is never persisted, so DB-default timestamps
    never fire. The response schema requires non-null datetimes, so the
    projection must carry the registry item's own timestamps."""
    ts = datetime(2024, 1, 2, 3, 4, 5)
    server = _project_catalog_mcp_server(_item(ts=ts))
    assert server.created_at == ts
    assert server.updated_at == ts


def test_catalog_item_normalizes_missing_timestamps():
    """Legacy registry rows can have NULL timestamps; API responses still
    require concrete datetimes."""

    class Row:
        def __init__(self):
            self.id = uuid4()
            self.name = "Legacy"
            self.description = "desc"
            self.version = "1"
            self.spec = {"connection_type": "url", "url": "https://x"}
            self.tags = ["url"]
            self.created_at = None
            self.updated_at = None

    from agentarea_mcp.infrastructure.catalog_mcp_repository import CatalogMcpRepository

    item = CatalogMcpRepository._row_to_item(Row(), registry_url=None)
    assert item.created_at is not None
    assert item.updated_at == item.created_at


def test_project_command_type_builds_cmd_and_bridge_image():
    item = _item(
        spec={"connection_type": "command", "command": "uvx", "args": ["pkg"], "env_schema": []}
    )
    server = _project_catalog_mcp_server(item)
    assert server.cmd == ["uvx", "pkg"]
    assert server.docker_image_url == "agentarea/mcp-bridge:latest"


@pytest.mark.asyncio
async def test_catalog_projections_shadows_instantiated_and_projects_rest():
    item_unforked = _item(name="Unforked")
    item_shadowed = _item(name="Shadowed")
    tenant_row = MCPServer(name="My copy", description="d")
    tenant_row.registry_item_id = item_shadowed.id

    repo = _repo(FakeCatalogRepo([item_unforked, item_shadowed]))
    projections = await repo._catalog_projections(
        [tenant_row], status=None, is_public=None, tag=None, search=None
    )
    ids = [str(s.id) for s in projections]

    assert item_unforked.id in ids
    assert item_shadowed.id not in ids
    assert all(getattr(s, "is_catalog", False) for s in projections)


@pytest.mark.asyncio
async def test_catalog_projections_apply_search_and_tag_filters():
    item = _item(name="Echo", tags=["url"], spec={"connection_type": "url", "url": "https://x"})
    repo = _repo(FakeCatalogRepo([item]))

    assert len(await repo._catalog_projections([], status=None, is_public=None, tag="url", search=None)) == 1
    assert len(await repo._catalog_projections([], status=None, is_public=None, tag="other", search=None)) == 0
    assert len(await repo._catalog_projections([], status=None, is_public=None, tag=None, search="echo")) == 1
    assert len(await repo._catalog_projections([], status=None, is_public=None, tag=None, search="zzz")) == 0


@pytest.mark.asyncio
async def test_isolation_builtin_visible_no_foreign_custom_leak():
    """A built-in catalog spec IS visible to every workspace; another workspace's
    custom spec is NOT (it never appears in this workspace's tenant rows, and only
    catalog items are merged in)."""
    item_builtin = _item(name="Shared built-in")
    repo = _repo(FakeCatalogRepo([item_builtin]))
    # No tenant rows (the base filter would exclude foreign customs); catalog global.
    projections = await repo._catalog_projections(
        [], status=None, is_public=None, tag=None, search=None
    )
    assert [str(s.id) for s in projections] == [item_builtin.id]
