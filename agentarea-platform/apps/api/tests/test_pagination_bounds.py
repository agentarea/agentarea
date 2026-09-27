"""A page or offset too large for a SQL OFFSET is a 422, not a 500.

Postgres takes OFFSET as a bigint; an unbounded ``page`` or ``offset`` query
parameter lets a request overflow it and fail inside the database. Every
such parameter the API publishes carries a maximum.
"""

import pytest
from agentarea_api.main import create_app

PAGING_PARAMS = {"page", "offset", "skip"}


@pytest.fixture(scope="module")
def schema() -> dict:
    return create_app().openapi()


def test_every_page_and_offset_parameter_is_bounded(schema: dict) -> None:
    unbounded = [
        f"{method.upper()} {path} ?{param['name']}"
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict)
        for param in operation.get("parameters", [])
        if param.get("in") == "query"
        and param["name"] in PAGING_PARAMS
        and "maximum" not in _integer_schema(param["schema"])
    ]
    assert unbounded == []


def _integer_schema(schema: dict) -> dict:
    for option in schema.get("anyOf", []):
        if option.get("type") == "integer":
            return option
    return schema
