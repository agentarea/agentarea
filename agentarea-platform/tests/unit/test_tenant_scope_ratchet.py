"""Raw SQL and tenant-scope bypasses only ever go down.

The ORM confines every workspace-scoped query to the bound workspace
(``agentarea_common.base.tenant_scope``), but it cannot see SQL it did not
build. The 2026-09 audit counted raw ``session.execute`` in production code
growing from 186 to 225 in a month, each one a query that has to remember the
workspace on its own.

Four things are counted per production module and held to the checked-in
baseline (``tenant_scope_ratchet_baseline.json``):

- ``text(`` calls outside repository modules,
- ``text(`` calls inside repository modules, apart from the above,
- ``<...>session.execute(`` calls outside repository modules,
- ``unscoped(`` call sites anywhere, each of which must also give a real reason.

Names imported under an alias (``from sqlalchemy import text as sql``) count
as the name they alias.

A count above the baseline fails: move the query into a repository, express
it through the ORM, or, for work that truly spans workspaces, justify it. A
count below the baseline also fails, so the lower number is written down and
cannot creep back: regenerate with

    uv run python tests/unit/test_tenant_scope_ratchet.py
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name("tenant_scope_ratchet_baseline.json")
KINDS = ("text", "repository_text", "session_execute", "unscoped")
ALIASED = {"text", "unscoped"}


def _production_modules() -> list[Path]:
    modules = []
    for root in ("libs", "apps"):
        for path in (PLATFORM_ROOT / root).glob("*/agentarea_*/**/*.py"):
            if "tests" not in path.relative_to(PLATFORM_ROOT).parts:
                modules.append(path)
    return sorted(modules)


def _is_repository(path: Path) -> bool:
    return "repositor" in path.name or "repositories" in path.parts


def _aliases(tree: ast.AST) -> dict[str, str]:
    return {
        alias.asname: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.asname and alias.name in ALIASED
    }


def _called_name(call: ast.Call, aliases: dict[str, str]) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return aliases.get(func.id, func.id)
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_sqlalchemy_text(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return True
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in {"sa", "sqlalchemy"}
    )


def _is_session_execute(call: ast.Call) -> bool:
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "execute"):
        return False
    target = func.value
    name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
    return name.endswith("session")


def _scan_source(source: str, *, repository: bool) -> tuple[Counter[str], list[int]]:
    """Counts by kind, and the lines of ``unscoped`` calls with no real reason."""
    counts: Counter[str] = Counter()
    weak_lines: list[int] = []
    tree = ast.parse(source)
    aliases = _aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node, aliases)
        if name == "unscoped":
            counts["unscoped"] += 1
            reason = node.args[0] if node.args else None
            said = reason.value if isinstance(reason, ast.Constant) else None
            if not isinstance(said, str) or len(said.strip()) <= 20:
                weak_lines.append(node.lineno)
        elif name == "text" and _is_sqlalchemy_text(node):
            counts["repository_text" if repository else "text"] += 1
        elif not repository and _is_session_execute(node):
            counts["session_execute"] += 1
    return counts, weak_lines


def _scan(path: Path) -> tuple[Counter[str], list[str]]:
    counts, weak_lines = _scan_source(
        path.read_text(encoding="utf-8"), repository=_is_repository(path)
    )
    where = path.relative_to(PLATFORM_ROOT)
    return counts, [f"{where}:{line}" for line in weak_lines]


def _current() -> tuple[dict[str, dict[str, int]], list[str]]:
    current: dict[str, dict[str, int]] = {kind: {} for kind in KINDS}
    weak: list[str] = []
    for path in _production_modules():
        counts, weak_reasons = _scan(path)
        weak.extend(weak_reasons)
        for kind, count in counts.items():
            current[kind][str(path.relative_to(PLATFORM_ROOT))] = count
    return current, weak


def _baseline() -> dict[str, dict[str, int]]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_the_scan_sees_the_code_it_guards() -> None:
    """Guard against a scan that silently finds nothing."""
    current, _weak = _current()
    assert sum(current["session_execute"].values()) > 50
    assert sum(current["text"].values()) > 10
    assert sum(current["repository_text"].values()) > 10
    assert sum(current["unscoped"].values()) > 5


def test_aliased_imports_and_repository_text_are_counted() -> None:
    source = (
        "from sqlalchemy import text as sql\n"
        "from agentarea_common.base.tenant_scope import unscoped as bypass\n"
        "sql('select 1')\n"
        "with bypass('short'):\n"
        "    pass\n"
    )
    counts, weak = _scan_source(source, repository=True)
    assert counts == {"repository_text": 1, "unscoped": 1}
    assert weak == [4]
    counts, _weak = _scan_source(source, repository=False)
    assert counts == {"text": 1, "unscoped": 1}


def test_every_unscoped_call_gives_a_real_reason() -> None:
    _current_counts, weak = _current()
    assert not weak, (
        "unscoped() needs a literal reason saying why the work spans workspaces:\n  "
        + "\n  ".join(weak)
    )


def test_raw_sql_and_bypasses_do_not_grow() -> None:
    current, _weak = _current()
    baseline = _baseline()
    grown = []
    shrunk = []
    for kind in KINDS:
        for module in sorted(set(current[kind]) | set(baseline.get(kind, {}))):
            now = current[kind].get(module, 0)
            then = baseline.get(kind, {}).get(module, 0)
            if now > then:
                grown.append(f"{kind}: {module} {then} -> {now}")
            elif now < then:
                shrunk.append(f"{kind}: {module} {then} -> {now}")
    assert not grown, (
        "raw SQL or tenant-scope bypasses grew:\n  "
        + "\n  ".join(grown)
        + "\n\nMove the query into a repository or express it through the ORM, where the "
        "workspace scope applies. Work that truly spans workspaces runs inside "
        "unscoped(reason); lift the baseline only with that reason in the diff."
    )
    assert not shrunk, (
        "fewer than the baseline -- lower it so the gain is kept:\n  "
        + "\n  ".join(shrunk)
        + "\n\n  uv run python tests/unit/test_tenant_scope_ratchet.py"
    )


if __name__ == "__main__":
    counts, _ = _current()
    BASELINE.write_text(
        json.dumps({k: dict(sorted(counts[k].items())) for k in KINDS}, indent=2) + "\n",
        encoding="utf-8",
    )
    sys.stdout.write(f"wrote {BASELINE.relative_to(PLATFORM_ROOT)}\n")
