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

# {toolset name: (group, {method: effect})}
Toolsets = dict[str, tuple[str | None, dict[str, str | None]]]
ToolsetLookup = Callable[[], Toolsets]


@functools.cache
def code_toolsets() -> Toolsets:
    """Every platform toolset by the name the model calls it, with its methods' effects."""
    from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata

    return {
        namespace.rsplit("/", 1)[-1]: (
            meta.get("group"),
            {m["name"]: m.get("effect") for m in meta.get("available_methods") or []},
        )
        for namespace, meta in get_code_tools_metadata().items()
    }


def _classify(
    tool_name: str, tool_args: dict[str, Any], toolsets: Toolsets
) -> tuple[str | None, str | None]:
    """The (group, effect) of one call; unknown parts come back ``None``.

    A toolset is called by its name, with ``action`` naming the method when it
    has more than one; a ``<toolset>_<method>`` name is understood as well.
    """
    if tool_name in toolsets:
        group, methods = toolsets[tool_name]
        if len(methods) == 1:
            return group, next(iter(methods.values()))
        return group, methods.get(str(tool_args.get("action") or ""))
    for name, (group, methods) in toolsets.items():
        method = tool_name.removeprefix(f"{name}_")
        if method != tool_name and method in methods:
            return group, methods[method]
    return None, None


@dataclass(frozen=True)
class EvaluationDecision:
    execute: bool
    stubbed: bool = False
    result: Any = None
    reason: str = ""


def evaluation_decision(
    tool_name: str,
    tool_args: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    *,
    is_mcp: bool,
    lookup: ToolsetLookup = code_toolsets,
) -> EvaluationDecision | None:
    """``None`` for an ordinary run; otherwise whether and how the call runs."""
    evaluation = (metadata or {}).get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    stubs = evaluation.get("stubs") or {}
    if tool_name in stubs:
        return EvaluationDecision(execute=False, stubbed=True, result=stubs[tool_name])
    if not is_mcp:
        group, effect = _classify(tool_name, tool_args or {}, lookup())
        if effect == "read":
            return EvaluationDecision(execute=True)
        if group == _SANDBOX_GROUP and effect and evaluation.get("sandbox_allowed") is True:
            return EvaluationDecision(execute=True)
    return EvaluationDecision(
        execute=False,
        reason=(
            f"{tool_name} was not executed: this is an evaluation run and the call could act "
            "outside it. Give the case a stub for this tool to answer it."
        ),
    )
