"""Semantic tool access API.

This is the product-facing API for granting and checking whether a user may
call a tool. The underlying graph can be OpenFGA, Keto, or another backend; API
consumers should not have to construct graph object keys or know namespaces.
"""

from __future__ import annotations

from typing import Any, Literal

from agentarea_common.auth import UserContextDep
from agentarea_common.auth.tool_invocation import (
    is_tool_invocation_allowed,
    tool_object_id,
    tool_resource_object_id,
)
from agentarea_common.rebac import (
    KetoError,
    KetoUnavailableError,
    OpenFGAClient,
    OpenFGAError,
    OpenFGAUnavailableError,
    RelationQuery,
    RelationTuple,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .access_control import _assert_workspace_admin, get_graph_client

router = APIRouter(prefix="/tool-access", tags=["tool-access"])


class ToolAccessGrantRequest(BaseModel):
    user_id: str = Field(..., description="User UUID or User:<uuid> subject.")
    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any] | None = Field(
        default=None,
        description="Optional exact argument set. Omit for a whole-tool grant.",
    )


class ToolAccessCheckRequest(BaseModel):
    user_id: str = Field(..., description="User UUID or User:<uuid> subject.")
    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any] | None = Field(
        default=None,
        description="Optional exact argument set. Omit to check the whole-tool grant.",
    )


class ToolAccessGrant(BaseModel):
    scope: Literal["tool", "arguments"]
    user_id: str
    tool_name: str
    object_id: str
    arguments_hash: str | None = None


class ToolAccessGrantResponse(BaseModel):
    ok: bool
    grant: ToolAccessGrant


class ToolAccessCheckResponse(BaseModel):
    allowed: bool
    grant: ToolAccessGrant


class ToolAccessGrantListResponse(BaseModel):
    grants: list[ToolAccessGrant]
    count: int


def _user_subject(user_id: str) -> str:
    return user_id if user_id.startswith("User:") else f"User:{user_id}"


def _user_id_from_subject(subject: str) -> str:
    return subject.split(":", 1)[1] if subject.startswith("User:") else subject


def _grant_for_payload(
    user_id: str, tool_name: str, arguments: dict[str, Any] | None
) -> ToolAccessGrant:
    if arguments is None:
        return ToolAccessGrant(
            scope="tool",
            user_id=_user_id_from_subject(_user_subject(user_id)),
            tool_name=tool_name,
            object_id=tool_object_id(tool_name),
        )

    object_id = tool_resource_object_id(tool_name, arguments)
    arguments_hash = object_id.rsplit("~args~", 1)[1] if "~args~" in object_id else None
    return ToolAccessGrant(
        scope="arguments",
        user_id=_user_id_from_subject(_user_subject(user_id)),
        tool_name=tool_name,
        object_id=object_id,
        arguments_hash=arguments_hash,
    )


def _graph_relationship_for_grant(grant: ToolAccessGrant) -> RelationTuple:
    return RelationTuple(
        namespace="Tool" if grant.scope == "tool" else "ToolResource",
        object=grant.object_id,
        relation="callers",
        subject_id=_user_subject(grant.user_id),
    )


def _grant_from_graph_relationship(relationship: RelationTuple) -> ToolAccessGrant | None:
    if relationship.relation != "callers" or not relationship.subject_id:
        return None
    if not relationship.subject_id.startswith("User:"):
        return None
    if relationship.namespace == "Tool":
        return ToolAccessGrant(
            scope="tool",
            user_id=_user_id_from_subject(relationship.subject_id),
            tool_name=relationship.object,
            object_id=relationship.object,
        )
    if relationship.namespace == "ToolResource":
        tool_name = relationship.object.split("~args~", 1)[0]
        arguments_hash = (
            relationship.object.rsplit("~args~", 1)[1] if "~args~" in relationship.object else None
        )
        return ToolAccessGrant(
            scope="arguments",
            user_id=_user_id_from_subject(relationship.subject_id),
            tool_name=tool_name,
            object_id=relationship.object,
            arguments_hash=arguments_hash,
        )
    return None


def _openfga_graph():
    graph = get_graph_client()
    return graph if isinstance(graph, OpenFGAClient) else None


@router.get("/grants", response_model=ToolAccessGrantListResponse)
async def list_tool_access_grants(
    user_context: UserContextDep,
) -> ToolAccessGrantListResponse:
    """List tool access grants in the configured graph backend."""
    del user_context
    graph = _openfga_graph()
    if graph is None:
        return ToolAccessGrantListResponse(grants=[], count=0)

    grants: list[ToolAccessGrant] = []
    try:
        for namespace in ("Tool", "ToolResource"):
            relationships = await graph.query_all_tuples(RelationQuery(namespace=namespace))
            for relationship in relationships:
                grant = _grant_from_graph_relationship(relationship)
                if grant is not None:
                    grants.append(grant)
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        raise HTTPException(status_code=503, detail="Tool access grants unavailable") from exc

    return ToolAccessGrantListResponse(grants=grants, count=len(grants))


@router.post("/grants", status_code=201, response_model=ToolAccessGrantResponse)
async def grant_tool_access(
    payload: ToolAccessGrantRequest,
    user_context: UserContextDep,
) -> ToolAccessGrantResponse:
    """Grant a user access to a whole tool, or to an exact argument set."""
    graph = _openfga_graph()
    if graph is None:
        raise HTTPException(status_code=503, detail="Tool access graph is disabled")

    await _assert_workspace_admin(user_context)
    grant = _grant_for_payload(payload.user_id, payload.tool_name, payload.arguments)
    try:
        await graph.write_tuple(_graph_relationship_for_grant(grant))
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        raise HTTPException(status_code=503, detail="Tool access grant failed") from exc
    return ToolAccessGrantResponse(ok=True, grant=grant)


@router.delete("/grants", status_code=204)
async def revoke_tool_access(
    payload: ToolAccessGrantRequest,
    user_context: UserContextDep,
) -> None:
    """Revoke a whole-tool or exact-arguments grant."""
    graph = _openfga_graph()
    if graph is None:
        raise HTTPException(status_code=503, detail="Tool access graph is disabled")

    await _assert_workspace_admin(user_context)
    grant = _grant_for_payload(payload.user_id, payload.tool_name, payload.arguments)
    try:
        await graph.delete_tuple(_graph_relationship_for_grant(grant))
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        raise HTTPException(status_code=503, detail="Tool access revoke failed") from exc


@router.post("/checks", response_model=ToolAccessCheckResponse)
async def check_tool_access(
    payload: ToolAccessCheckRequest,
    user_context: UserContextDep,
) -> ToolAccessCheckResponse:
    """Check whether a user can call a tool.

    Omitting ``arguments`` checks a whole-tool grant. Passing ``arguments``
    checks the concrete invocation path used by runtime tool execution.
    """
    del user_context
    graph = _openfga_graph()
    grant = _grant_for_payload(payload.user_id, payload.tool_name, payload.arguments)
    if graph is None:
        return ToolAccessCheckResponse(allowed=False, grant=grant)

    try:
        if payload.arguments is None:
            result = await graph.check(
                namespace="Tool",
                object=tool_object_id(payload.tool_name),
                relation="can_call",
                subject_id=_user_subject(payload.user_id),
            )
            allowed = result.allowed
        else:
            allowed = await is_tool_invocation_allowed(
                graph,
                user_id=_user_id_from_subject(_user_subject(payload.user_id)),
                tool_name=payload.tool_name,
                tool_args=payload.arguments,
            )
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        raise HTTPException(status_code=503, detail="Tool access check failed") from exc

    return ToolAccessCheckResponse(allowed=allowed, grant=grant)
