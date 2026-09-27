"""JSON that Postgres can store as jsonb and read back as text.

A NUL or an unpaired UTF-16 surrogate is valid JSON, but jsonb refuses it and
``->>`` on a plain ``json`` column fails to render it, so one such value
written through the API used to break every later query that read the column.
"""

from __future__ import annotations

import pytest
from agentarea_common.utils.pg_text import pg_text_problem


@pytest.mark.parametrize(
    "value",
    [
        {"type": "docker", "env": {"A": "b"}, "args": ["-v", 1, None, True]},
        {"name": "ремонт \U0001f527"},
        {},
    ],
)
def test_ordinary_json_is_accepted(value) -> None:
    assert pg_text_problem(value) is None


@pytest.mark.parametrize(
    ("value", "where"),
    [
        ({"a": "x\x00y"}, "$.a"),
        ({"a": [{"b": "\x00"}]}, "$.a[0].b"),
        ({"k\x00": 1}, "$"),
        ({"a": "\ud958"}, "$.a"),
        ({"a": ["ok", "\udf71x"]}, "$.a[1]"),
    ],
)
def test_nul_and_lone_surrogates_are_located(value, where) -> None:
    problem = pg_text_problem(value)

    assert problem is not None
    assert where in problem
