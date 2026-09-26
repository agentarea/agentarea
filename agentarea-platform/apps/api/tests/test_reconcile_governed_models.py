"""The reconcile script walks every model that declares ``__graph_resource__``.

``graph_governed_models()`` reads the SQLAlchemy registry, which holds only the
models something has imported. The script used to import five of them by hand,
so triggers, OpenAPI connections and skill collections were never mapped in its
process and their rows got no ownership repair. The expected set is read off the
source, so a newly governed model fails this test until the script walks it.

Run in a fresh interpreter: inside pytest, other tests have already imported
every model, which would hide exactly this gap.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[3]
_SCRIPT = _PLATFORM / "scripts" / "20260923_reconcile_resource_authz.py"

_PROBE = f"""
import importlib.util, json
spec = importlib.util.spec_from_file_location("_reconcile", {str(_SCRIPT)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(sorted(m.__tablename__ for m in module.load_governed_models())))
"""


def _declared_governed_tables() -> set[str]:
    tables: set[str] = set()
    for root in (_PLATFORM / "libs", _PLATFORM / "apps"):
        for path in root.rglob("*.py"):
            if "tests" in path.relative_to(_PLATFORM).parts or ".venv" in path.parts:
                continue
            source = path.read_text()
            if "__graph_resource__" not in source:
                continue
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.ClassDef):
                    continue
                attrs = {
                    target.id: statement.value
                    for statement in node.body
                    if isinstance(statement, ast.Assign)
                    for target in statement.targets
                    if isinstance(target, ast.Name)
                }
                flag = attrs.get("__graph_resource__")
                table = attrs.get("__tablename__")
                if (
                    isinstance(flag, ast.Constant)
                    and flag.value is True
                    and isinstance(table, ast.Constant)
                ):
                    tables.add(table.value)
    return tables


def test_the_script_walks_every_model_declared_governed():
    probe = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=False,
        cwd=_PLATFORM,
    )
    assert probe.returncode == 0, probe.stderr

    walked = set(json.loads(probe.stdout.strip().splitlines()[-1]))

    declared = _declared_governed_tables()
    assert {"triggers", "openapi_connections", "skill_collections"} <= declared
    assert walked == declared
