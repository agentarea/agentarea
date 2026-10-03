"""MCP server spec catalog read-path tests (ADR-003).

Built-in MCP server specs live in the registry catalog (``registry_items`` of
``registry_type='mcp_servers'``) and are merged into the spec list read-only.
Unlike agents/skills there is no copy-on-write fork: built-in specs are
reference specs users instantiate via ``mcp_server_instances``. These tests
cover the projection itself; the merged list runs against the real schema in
``test_mcp_spec_list_db.py``.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.infrastructure.catalog_mcp_repository import CatalogMcpItem
from agentarea_mcp.infrastructure.repository import (
    MCPServerRepository,
    _project_catalog_mcp_server,
)
from sqlalchemy import true

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


def test_project_command_type_builds_cmd_and_base_image():
    item = _item(
        spec={"connection_type": "command", "command": "uvx", "args": ["pkg"], "env_schema": []}
    )
    server = _project_catalog_mcp_server(item)
    assert server.cmd == ["uvx", "pkg"]
    assert server.docker_image_url == "agentarea/agentarea-mcp-base"


def test_project_derives_schema_from_raw_package_environment_variables():
    item = _item(
        spec={
            "connection_type": "command",
            "package_registry": "pypi",
            "package_name": "distribution-name",
            "raw_spec": {
                "packages": [
                    {
                        "registryType": "pypi",
                        "name": "distribution-name",
                        "environmentVariables": [
                            {
                                "name": "API_TOKEN",
                                "description": "API credential",
                                "isSecret": True,
                                "isRequired": True,
                            }
                        ],
                    }
                ]
            },
        }
    )

    server = _project_catalog_mcp_server(item)

    assert server.env_schema == [
        {
            "name": "API_TOKEN",
            "description": "API credential",
            "isSecret": True,
            "isRequired": True,
            "required": True,
        }
    ]


def test_project_derives_schema_from_raw_remote_headers():
    item = _item(
        spec={
            "connection_type": "url",
            "url": "https://api.example.test/mcp",
            "raw_spec": {
                "remotes": [
                    {
                        "url": "https://api.example.test/mcp",
                        "headers": [
                            {
                                "name": "Authorization",
                                "description": "Bearer credential",
                                "isSecret": True,
                                "isRequired": True,
                            }
                        ],
                    }
                ]
            },
        }
    )

    server = _project_catalog_mcp_server(item)

    assert server.env_schema[0]["name"] == "Authorization"
    assert server.env_schema[0]["isSecret"] is True
    assert server.env_schema[0]["isRequired"] is True


async def test_synced_catalog_row_derives_env_schema_from_its_catalog_item():
    item = _item(
        spec={
            "connection_type": "command",
            "package_registry": "pypi",
            "package_name": "distribution-name",
            "env_schema": [],
            "raw_spec": {
                "packages": [
                    {
                        "registryType": "pypi",
                        "name": "distribution-name",
                        "environmentVariables": [
                            {"name": "API_TOKEN", "isSecret": True, "isRequired": True}
                        ],
                    }
                ]
            },
        }
    )
    server = MCPServer(
        name="Synced",
        slug="synced",
        description="",
        status="active",
        workspace_id="platform",
        created_by="platform",
        registry_item_id=item.id,
        json_spec=item.spec["raw_spec"],
        env_schema=[],
    )
    server.id = item.id

    repo = MCPServerRepository.__new__(MCPServerRepository)
    repo.model_class = MCPServer
    repo.session = MagicMock()
    repo.session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=server))
    )
    repo._get_workspace_filter = MagicMock(return_value=true())
    catalog_repo = MagicMock()
    catalog_repo.get_item = AsyncMock(return_value=item)
    repo._get_catalog_repository = MagicMock(return_value=catalog_repo)

    result = await repo.get_server_by_id(str(item.id))

    assert result is server
    assert server.env_schema[0]["name"] == "API_TOKEN"
    assert server.env_schema[0]["isSecret"] is True
