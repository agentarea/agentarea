"""The owner-name resolver's map has to stay paired with the catalog's list.

A surfaced owner type with no table resolves to no name, so the page would show
"owner missing" for a connection that exists — and the failure would be silent.
"""

from agentarea_api.api.v1._secret_owners import _OWNER_TABLES
from agentarea_secrets.catalog_service import SURFACED_OWNER_TYPES


def test_every_surfaced_owner_type_can_be_resolved() -> None:
    assert set(_OWNER_TABLES) == set(SURFACED_OWNER_TYPES)
