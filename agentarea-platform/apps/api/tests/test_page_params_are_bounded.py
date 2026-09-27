"""Every ``page`` query parameter has an upper bound.

An unbounded page becomes an OFFSET the database driver cannot encode, and the
request answers 500. The live-stack fuzz found it on /skills, then on /inbox:
each route that declares its own ``page`` has to carry the bound, so this
checks all of them rather than one.
"""

from agentarea_api.main import app


def _unbounded_page_params() -> list[str]:
    unbounded = []
    for path, item in app.openapi()["paths"].items():
        for method, operation in item.items():
            for param in operation.get("parameters", []):
                if param.get("in") != "query" or param.get("name") != "page":
                    continue
                schema = param.get("schema", {})
                if "maximum" not in schema:
                    unbounded.append(f"{method.upper()} {path}")
    return unbounded


def test_every_page_parameter_is_bounded():
    assert _unbounded_page_params() == []
