"""The topology shows the workspace the path selects, not every workspace the caller reaches.

The workspace is named in the URL; a member of two workspaces asking for one
must not see the other's agents, skills or connections mixed in.
Cross-workspace rollups were rejected as a product shape.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_api.api.v1.network import get_network_topology
from agentarea_common.auth.context import UserContext
from agentarea_common.di.container import register_singleton
from agentarea_common.features.service import FeatureService


def _recording_database(statements: list) -> MagicMock:
    async def execute(statement, *args, **kwargs):
        statements.append(statement)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.__iter__ = lambda self: iter([])
        return result

    @asynccontextmanager
    async def session():
        yield MagicMock(execute=AsyncMock(side_effect=execute))

    database = MagicMock()
    database.session = session
    return database


@pytest.mark.asyncio
async def test_only_the_selected_workspace_is_read():
    register_singleton(FeatureService, FeatureService())
    statements: list = []
    context = UserContext(
        user_id="alice",
        workspace_id="ws-selected",
        workspace_slug="selected",
        accessible_workspaces=["ws-selected", "ws-other"],
    )

    with patch(
        "agentarea_common.config.database.get_database",
        return_value=_recording_database(statements),
    ):
        await get_network_topology(context)

    assert statements, "the handler issued no queries"
    bound = [value for s in statements for value in s.compile().params.values()]
    flattened = [v for value in bound for v in (value if isinstance(value, list) else [value])]
    assert "ws-selected" in flattened
    assert "ws-other" not in flattened
