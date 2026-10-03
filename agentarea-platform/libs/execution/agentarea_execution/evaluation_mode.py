"""What a tool call does inside an evaluation run.

An evaluation run is a real task whose metadata carries ``evaluation``. Its
tool calls must not reach anything outside the run: read-only platform tools
run, sandbox tools run inside the run's own fresh sandbox when the evaluation
run allowed it, a stubbed tool answers with its stub, and everything else is
not executed. MCP tools never run for real without a stub: their read-only
hints are the server's claim, not something the platform verified.
"""

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

NOT_EXECUTED = "not_executed_in_evaluation"
_SANDBOX_GROUP = "sandbox"

EffectLookup = Callable[[], dict[str, tuple[str | None, str | None]]]


@functools.cache
def code_tool_effects() -> dict[str, tuple[str | None, str | None]]:
    """``{tool name: (toolset group, method effect)}`` for every platform toolset."""
    from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata

    effects: dict[str, tuple[str | None, str | None]] = {}
    for namespace, meta in get_code_tools_metadata().items():
        prefix = namespace.rsplit("/", 1)[-1]
        for method in meta.get("available_methods") or []:
            effects[f"{prefix}_{method['name']}"] = (meta.get("group"), method.get("effect"))
    return effects


@dataclass(frozen=True)
class EvaluationDecision:
    execute: bool
    stubbed: bool = False
    result: Any = None
    reason: str = ""


def evaluation_decision(
    tool_name: str,
    metadata: dict[str, Any] | None,
    *,
    is_mcp: bool,
    lookup: EffectLookup = code_tool_effects,
) -> EvaluationDecision | None:
    """``None`` for an ordinary run; otherwise whether and how the call runs."""
    evaluation = (metadata or {}).get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    stubs = evaluation.get("stubs") or {}
    if tool_name in stubs:
        return EvaluationDecision(execute=False, stubbed=True, result=stubs[tool_name])
    if not is_mcp:
        group, effect = lookup().get(tool_name, (None, None))
        if effect == "read":
            return EvaluationDecision(execute=True)
        if group == _SANDBOX_GROUP and evaluation.get("sandbox_allowed") is True:
            return EvaluationDecision(execute=True)
    return EvaluationDecision(
        execute=False,
        reason=(
            f"{tool_name} was not executed: this is an evaluation run and the call could act "
            "outside it. Give the case a stub for this tool to answer it."
        ),
    )
