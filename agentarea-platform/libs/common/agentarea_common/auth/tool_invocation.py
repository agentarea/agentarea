"""Authorization helpers for concrete tool invocations.

Tool invocation authorization is intentionally modeled as an exact runtime
resource: a user may be allowed to call a tool broadly, or only with a specific
canonical argument set.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import quote

from ..rebac.models import RelationTuple
from ..rebac.openfga_client import OpenFGAClient, OpenFGAError


def tool_object_id(tool_name: str, workspace_id: str | None = None) -> str:
    """Return the stable OpenFGA object id for a tool in a workspace."""
    encoded_tool = quote(str(tool_name), safe="-._~")
    if workspace_id is None:
        return encoded_tool
    encoded_workspace = quote(str(workspace_id), safe="-._~")
    return f"{encoded_workspace}/{encoded_tool}"


def canonical_tool_args(tool_args: dict[str, Any] | None) -> str:
    """Serialize tool args deterministically for exact parameter grants."""
    return json.dumps(tool_args or {}, sort_keys=True, separators=(",", ":"), default=str)


def tool_resource_object_id(
    tool_name: str, tool_args: dict[str, Any] | None, workspace_id: str | None = None
) -> str:
    """Return the OpenFGA object id for this exact tool invocation."""
    args_hash = hashlib.sha256(canonical_tool_args(tool_args).encode()).hexdigest()
    return f"{tool_object_id(tool_name, workspace_id)}~args~{args_hash}"


def tool_workspace_tuple(tool_name: str, workspace_id: str) -> RelationTuple:
    """Contextual tuple placing the broad tool inside a workspace."""
    return RelationTuple(
        namespace="Tool",
        object=tool_object_id(tool_name, workspace_id),
        relation="workspace",
        subject_id=f"Workspace:{workspace_id}",
    )


def workspace_member_tuple(workspace_id: str, user_id: str) -> RelationTuple:
    """Contextual tuple proving the checked user belongs to the workspace."""
    return RelationTuple(
        namespace="Workspace",
        object=workspace_id,
        relation="members",
        subject_id=f"User:{user_id}",
    )


def tool_resource_workspace_tuple(
    tool_name: str, tool_args: dict[str, Any] | None, workspace_id: str
) -> RelationTuple:
    """Contextual tuple placing the exact invocation resource inside a workspace."""
    return RelationTuple(
        namespace="ToolResource",
        object=tool_resource_object_id(tool_name, tool_args, workspace_id),
        relation="workspace",
        subject_id=f"Workspace:{workspace_id}",
    )


def tool_resource_link_tuple(
    tool_name: str, tool_args: dict[str, Any] | None, workspace_id: str | None = None
) -> RelationTuple:
    """Contextual tuple linking an exact invocation resource to its broad tool."""
    return RelationTuple(
        namespace="ToolResource",
        object=tool_resource_object_id(tool_name, tool_args, workspace_id),
        relation="tool",
        subject_id=f"Tool:{tool_object_id(tool_name, workspace_id)}",
    )


async def is_tool_invocation_allowed(
    openfga: OpenFGAClient,
    *,
    user_id: str | None,
    workspace_id: str | None,
    tool_name: str,
    tool_args: dict[str, Any] | None,
) -> bool:
    """Check whether a user may execute this concrete tool invocation.

    Grants supported by the model:
    - Broad: ``Tool:<tool>#callers@User:<user>``.
    - Exact args: ``ToolResource:<tool>~args~<sha256>#callers@User:<user>``.

    No user/workspace id, OpenFGA errors, and false checks all deny.
    """
    if not user_id or not workspace_id:
        return False
    try:
        result = await openfga.check(
            namespace="ToolResource",
            object=tool_resource_object_id(tool_name, tool_args, workspace_id),
            relation="can_call",
            subject_id=f"User:{user_id}",
            contextual_tuples=[
                workspace_member_tuple(workspace_id, user_id),
                tool_workspace_tuple(tool_name, workspace_id),
                tool_resource_workspace_tuple(tool_name, tool_args, workspace_id),
                tool_resource_link_tuple(tool_name, tool_args, workspace_id),
            ],
        )
    except OpenFGAError:
        return False
    return result.allowed
