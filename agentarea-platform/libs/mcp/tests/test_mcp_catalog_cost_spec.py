"""An MCP connection's cost is read from the catalog's server JSON, never a member's copy."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from agentarea_mcp.infrastructure.catalog_mcp_repository import CatalogMcpItem
from agentarea_mcp.infrastructure.repository import MCPServerRepository

CATALOG_JSON = {"name": "com.vendor/mcp", "metadata": {"agentarea:cost": {"default": {"source": "free"}}}}
EDITED_JSON = {
    "name": "com.vendor/mcp",
    "metadata": {
        "agentarea:cost": {
            "default": {
                "source": "settled",
                "settled": {
                    "fetch": {
                        "url": "https://collector.example/{id}",
                        "params": {"id": "$.id"},
                        "cost": "$.cost",
                        "currency": "USD",
                    }
                },
            }
        }
    },
}


def _repository(server, item=None):
    repository = MCPServerRepository(MagicMock(), SimpleNamespace(workspace_id="w", user_id="u"))
    repository.get_server_by_id = AsyncMock(return_value=server)
    catalog = SimpleNamespace(get_item=AsyncMock(return_value=item))
    repository._get_catalog_repository = lambda: catalog
    return repository, catalog


def _server(*, workspace_id="w", registry_item_id=None, json_spec=EDITED_JSON):
    return SimpleNamespace(
        is_catalog=False,
        workspace_id=workspace_id,
        registry_item_id=registry_item_id,
        json_spec=json_spec,
    )


def _item(item_id):
    return CatalogMcpItem(
        id=str(item_id),
        name="Vendor",
        description="",
        version="1",
        spec={"connection_type": "url", "url": "https://mcp.vendor.example", "raw_spec": CATALOG_JSON},
        tags=[],
        registry_url=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


async def test_a_workspace_copy_of_a_catalog_spec_reads_the_catalog_item():
    item_id = uuid4()
    repository, catalog = _repository(_server(registry_item_id=item_id), _item(item_id))

    assert await repository.catalog_json_spec(uuid4()) == CATALOG_JSON
    catalog.get_item.assert_awaited_once_with(str(item_id))


async def test_a_spec_a_member_wrote_declares_nothing():
    repository, _ = _repository(_server())

    assert await repository.catalog_json_spec(uuid4()) is None


async def test_the_platforms_own_row_is_the_catalog():
    repository, _ = _repository(_server(workspace_id=PLATFORM_WORKSPACE_ID, json_spec=CATALOG_JSON))

    assert await repository.catalog_json_spec(uuid4()) == CATALOG_JSON
