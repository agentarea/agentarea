"""Deterministic checks over the outcome of one evaluation trial.

No LLM judges here: a check either holds on the recorded outcome or it does not.
A run that did not complete fails unless a case checks its status explicitly.
"""

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any


@dataclass(frozen=True)
class TrialOutcome:
    status: str
    response: str
    cost_usd: float = 0.0
    iterations: int = 0
    tools_called: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


_FIELDS: dict[str, dict[str, type]] = {
    "status_is": {"status": str},
    "response_contains": {"text": str},
    "response_not_contains": {"text": str},
    "response_matches": {"pattern": str},
    "tool_called": {"tool": str},
    "tool_not_called": {"tool": str},
    "artifact_exists": {"glob": str},
    "max_cost": {"usd": float},
    "max_iterations": {"count": int},
}
_OPTIONAL = {"case_sensitive": bool}


def validate_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the checks normalized, or raise ``ValueError`` naming the first bad one."""
    normalized: list[dict[str, Any]] = []
    for index, check in enumerate(checks):
        kind = check.get("type")
        if kind not in _FIELDS:
            raise ValueError(f"check {index}: unknown check type {kind!r}")
        clean: dict[str, Any] = {"type": kind}
        for name, kind_of in _FIELDS[kind].items():
            if name not in check:
                raise ValueError(f"check {index} ({kind}): missing {name!r}")
            try:
                clean[name] = kind_of(check[name])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"check {index} ({kind}): {name!r} is not a {kind_of.__name__}"
                ) from error
        for name, kind_of in _OPTIONAL.items():
            if name in check:
                clean[name] = kind_of(check[name])
        if kind == "response_matches":
            try:
                re.compile(clean["pattern"])
            except re.error as error:
                raise ValueError(
                    f"check {index} (response_matches): bad pattern: {error}"
                ) from error
        normalized.append(clean)
    return normalized


def _contains(haystack: str, needle: str, case_sensitive: bool) -> bool:
    return needle in haystack if case_sensitive else needle.lower() in haystack.lower()


def _evaluate(check: dict[str, Any], outcome: TrialOutcome) -> tuple[bool, str]:
    kind = check["type"]
    case_sensitive = bool(check.get("case_sensitive", False))
    if kind == "status_is":
        return outcome.status == check["status"], outcome.status
    if kind == "response_contains":
        return _contains(outcome.response, check["text"], case_sensitive), "response checked"
    if kind == "response_not_contains":
        return not _contains(outcome.response, check["text"], case_sensitive), "response checked"
    if kind == "response_matches":
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.search(check["pattern"], outcome.response, flags) is not None, "response checked"
    if kind == "tool_called":
        return check["tool"] in outcome.tools_called, ", ".join(outcome.tools_called) or "no tools"
    if kind == "tool_not_called":
        return check["tool"] not in outcome.tools_called, ", ".join(
            outcome.tools_called
        ) or "no tools"
    if kind == "artifact_exists":
        found = [path for path in outcome.artifacts if fnmatch(path, check["glob"])]
        return bool(found), ", ".join(found) or "no matching artifact"
    if kind == "max_cost":
        return outcome.cost_usd <= check["usd"], f"${outcome.cost_usd:.4f}"
    if kind == "max_iterations":
        return outcome.iterations <= check["count"], f"{outcome.iterations} iterations"
    raise ValueError(f"unknown check type {kind!r}")


def run_checks(
    checks: list[dict[str, Any]], outcome: TrialOutcome
) -> tuple[bool, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    if not any(check["type"] == "status_is" for check in checks):
        completed = outcome.status in ("completed", "awaiting_follow_up")
        results.append({"type": "completed", "passed": completed, "detail": outcome.status})
    for check in checks:
        passed, detail = _evaluate(check, outcome)
        results.append({**check, "passed": passed, "detail": detail})
    return all(result["passed"] for result in results), results
