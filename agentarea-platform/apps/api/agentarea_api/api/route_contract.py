"""Checks the app's routes must pass before it is allowed to start.

A route that resolves a workspace context must say which workspace it acts in:
by carrying ``{workspace}`` in its path, or by binding the workspace of the
entity it addresses. A route that does neither can only fail at request time
(``WorkspaceNotSelectedError``), so it is refused at build time instead.
"""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from agentarea_common.auth.dependencies import (
    WORKSPACE_BINDER_ATTR,
    WORKSPACE_PATH_PARAM,
    get_user_context,
)
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute


class RouteContractError(RuntimeError):
    """The routes the app was built with break the workspace or operation-id contract."""


def _resolution_order(dependant: Dependant) -> list[Any]:
    """Dependency callables in the order FastAPI calls them, first call only.

    FastAPI resolves a dependency's own dependencies before calling it, in
    declaration order, and caches each result for the rest of the request.
    """
    order: list[Any] = []

    def visit(node: Dependant) -> None:
        for dependency in node.dependencies:
            visit(dependency)
            if dependency.call not in order:
                order.append(dependency.call)

    visit(dependant)
    return order


def check_route_contract(routes: Iterable[Any]) -> None:
    """Raise :class:`RouteContractError` listing every route that breaks the contract."""
    unselected: list[str] = []
    operations: dict[str, list[str]] = defaultdict(list)
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        label = f"{','.join(sorted(route.methods))} {route.path}"
        operations[route.operation_id or route.unique_id].append(label)

        order = _resolution_order(route.dependant)
        if get_user_context not in order:
            continue
        if f"{{{WORKSPACE_PATH_PARAM}}}" in route.path:
            continue
        # A binder that runs after get_user_context binds nothing in time for it.
        context_at = order.index(get_user_context)
        if any(getattr(call, WORKSPACE_BINDER_ATTR, False) for call in order[:context_at]):
            continue
        unselected.append(label)

    problems: list[str] = []
    if unselected:
        problems.append(
            "routes resolve a workspace context but neither carry "
            f"'{{{WORKSPACE_PATH_PARAM}}}' in their path nor bind one before it: "
            + "; ".join(unselected)
        )
    duplicated = {op: labels for op, labels in operations.items() if len(labels) > 1}
    if duplicated:
        problems.append(
            "operation ids are not unique: "
            + "; ".join(f"{op} -> {labels}" for op, labels in sorted(duplicated.items()))
        )
    if problems:
        raise RouteContractError("\n".join(problems))
