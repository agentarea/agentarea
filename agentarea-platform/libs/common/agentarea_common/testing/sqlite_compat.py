"""Cross-dialect compilation shims for SQLite-backed test databases.

Several models use Postgres-specific column types (``JSONB``, ``INET``). When a
test creates the schema on in-memory SQLite via ``metadata.create_all``, SQLite's
compiler can't render those types and raises ``CompileError``. Importing this
module registers ``@compiles(..., "sqlite")`` shims that map them onto SQLite
equivalents.

These shims fire ONLY for the ``sqlite`` dialect, so production (Postgres, where
the types are native) is unaffected. Import this module from a conftest before
any ``create_all`` runs.
"""

from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _render_jsonb_as_json_on_sqlite(element, compiler, **kw) -> str:
    # SQLite has a native JSON type (values stored as TEXT); good enough for the
    # dict round-tripping the tests exercise.
    return "JSON"


@compiles(INET, "sqlite")
def _render_inet_as_text_on_sqlite(element, compiler, **kw) -> str:
    return "TEXT"
