from uuid import UUID

from agentarea_mcp.domain.models import MCPServer


def test_registry_item_id_binds_as_uuid():
    """registry_item_id maps to a real Postgres uuid column.

    With as_uuid=False the asyncpg dialect binds the value as VARCHAR, which
    Postgres rejects against the uuid column on insert (the catalog reconcile
    failed with DatatypeMismatchError). Guard the binding type so it can't
    regress to a string bind.
    """
    col = MCPServer.__table__.c.registry_item_id
    assert col.type.python_type is UUID
    assert getattr(col.type, "as_uuid", False) is True
