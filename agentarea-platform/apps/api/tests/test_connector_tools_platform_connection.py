"""A platform-managed connection is platform data: every workspace may use it.

No tenant's graph names it and no person signs in to it; the operator does. Its calls
still pass the policy, the spend caps and, with billing installed, the balance.
"""

from types import SimpleNamespace
from uuid import uuid4

from agentarea_api.tools import connector_tools_toolset as toolset


def _connection(managed_by):
    return SimpleNamespace(
        id=uuid4(), registry_item_id=uuid4(), auth_config_id=None, managed_by=managed_by
    )


async def test_a_platform_connection_needs_no_sign_in():
    action = await toolset._openapi_connect_action(None, None, None, _connection("platform"))

    assert action is None


def test_only_platform_managed_rows_skip_the_graph():
    assert toolset._platform_managed(_connection("platform"))
    assert not toolset._platform_managed(_connection(None))
    assert not toolset._platform_managed(SimpleNamespace())
