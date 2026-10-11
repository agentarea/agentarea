"""Tool-call approvals: what an approval link opens, and the decision it records.

A client's call the workspace policy holds for approval is recorded and answered
with a link to ``/w/{slug}/approve/{id}``. The page reads the approval here and
posts the person's decision; the client's retry with the same arguments then
runs the call once.
"""

from typing import Annotated, Any

from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import enforced_in_handler, unrestricted
from agentarea_common.base import ReadRepositoryFactoryDep, RepositoryFactoryDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config import get_settings
from agentarea_common.utils.types import UtcDatetime
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_governance.application.tool_call_approvals import ToolCallApprovalService
from agentarea_governance.domain.tool_call_approvals import (
    NotAnApproverError,
    ToolCallApproval,
    ToolCallApprovalNotFoundError,
    ToolCallApprovalNotPendingError,
    ToolCallApprovalStatus,
)
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/tool-call-approvals", tags=["tool-call-approvals"])


def approval_page_url(workspace_slug: str, approval_id: str) -> str:
    """The page a person opens to approve one held call: an approval link."""
    frontend_base = get_settings().app.FRONTEND_BASE_URL.rstrip("/")
    if not frontend_base:
        raise RuntimeError("FRONTEND_BASE_URL is not set: an approval link has no page to point at")
    return f"{frontend_base}/w/{workspace_slug}/approve/{approval_id}"


class ToolCallApprovalResponse(BaseModel):
    id: str
    status: ToolCallApprovalStatus
    requested_by: str
    client_id: str | None
    client_name: str | None
    mcp_instance_id: str | None
    connector: str
    tool: str
    policy_name: str
    # The exact arguments that will run; only an approver or the requester sees them.
    arguments: dict[str, Any] | None
    reason: str
    # The tool's safety annotation on its server: "read-only", "destructive" or None.
    hint: str | None
    can_decide: bool
    decided_by: str | None
    decided_at: UtcDatetime | None
    comment: str | None
    expires_at: UtcDatetime
    created_at: UtcDatetime
    url: str


class ToolCallApprovalListResponse(BaseModel):
    items: list[ToolCallApprovalResponse]
    total: int
    page: int
    page_size: int


class ToolCallApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    comment: str | None = Field(default=None, max_length=2000)


async def _tool_hint(
    repository_factory: RepositoryFactory, approval: ToolCallApproval
) -> str | None:
    """The tool's safety hint as its connection last listed it."""
    if approval.mcp_instance_id is None:
        return None
    from agentarea_api.tools.mcp_servers_toolset import _tool_safety_hint
    from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository

    instance = await repository_factory.create_repository(MCPServerInstanceRepository).get_by_id(
        approval.mcp_instance_id
    )
    if instance is None:
        return None
    spec = next((t for t in instance.tools or [] if t.get("name") == approval.tool), None)
    return _tool_safety_hint(spec) if spec is not None else None


def _response(
    repository_factory: RepositoryFactory,
    approval: ToolCallApproval,
    *,
    workspace_slug: str,
    hint: str | None,
) -> ToolCallApprovalResponse:
    user_id = repository_factory.user_context.user_id
    can_decide = approval.status is ToolCallApprovalStatus.PENDING and (
        ToolCallApprovalService.may_decide(approval, user_id)
    )
    shows_arguments = ToolCallApprovalService.may_decide(approval, user_id) or (
        approval.requested_by == user_id
    )
    return ToolCallApprovalResponse(
        id=approval.id,
        status=approval.status,
        requested_by=approval.requested_by,
        client_id=approval.client_id,
        client_name=approval.client_name,
        mcp_instance_id=approval.mcp_instance_id,
        connector=approval.connector,
        tool=approval.tool,
        policy_name=approval.policy_name,
        arguments=approval.arguments if shows_arguments else None,
        reason=approval.reason,
        hint=hint,
        can_decide=can_decide,
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        comment=approval.comment,
        expires_at=approval.expires_at,
        created_at=approval.created_at,
        url=approval_page_url(workspace_slug, approval.id),
    )


async def _slug(repository_factory: RepositoryFactory) -> str:
    user_context = repository_factory.user_context
    return user_context.workspace_slug or await workspace_slug_for(user_context.workspace_id)


@router.get(
    "",
    response_model=ToolCallApprovalListResponse,
    dependencies=[
        unrestricted(
            "workspace member; the workspace-scoped repository is the boundary and the "
            "arguments go only to an approver or the requester"
        )
    ],
)
async def list_tool_call_approvals(
    user_context: UserContextDep,
    repository_factory: ReadRepositoryFactoryDep,
    status: Annotated[ToolCallApprovalStatus | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ToolCallApprovalListResponse:
    """Tool calls held for approval in this workspace, newest first."""
    approvals, total = await ToolCallApprovalService(repository_factory).list(
        status=status, limit=page_size, offset=(page - 1) * page_size
    )
    slug = await _slug(repository_factory)
    items = [
        _response(repository_factory, approval, workspace_slug=slug, hint=None)
        for approval in approvals
    ]
    return ToolCallApprovalListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/{approval_id}",
    response_model=ToolCallApprovalResponse,
    dependencies=[
        unrestricted(
            "workspace member; the workspace-scoped repository is the boundary and the "
            "arguments go only to an approver or the requester"
        )
    ],
)
async def get_tool_call_approval(
    approval_id: str,
    user_context: UserContextDep,
    repository_factory: ReadRepositoryFactoryDep,
) -> ToolCallApprovalResponse:
    """One held call: what will run, who asked, and whether the caller may decide."""
    approval = await ToolCallApprovalService(repository_factory).get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return _response(
        repository_factory,
        approval,
        workspace_slug=await _slug(repository_factory),
        hint=await _tool_hint(repository_factory, approval),
    )


@router.post(
    "/{approval_id}/decide",
    response_model=ToolCallApprovalResponse,
    dependencies=[
        enforced_in_handler(
            "only an approver the policy named on the approval may decide; with none "
            "named, any workspace member"
        )
    ],
)
async def decide_tool_call_approval(
    approval_id: str,
    payload: ToolCallApprovalDecision,
    user_context: UserContextDep,
    repository_factory: RepositoryFactoryDep,
) -> ToolCallApprovalResponse:
    """Approve or reject a pending call; an approval is usable for one hour."""
    try:
        decided = await ToolCallApprovalService(repository_factory).decide(
            approval_id, approved=payload.approved, comment=payload.comment or None
        )
    except ToolCallApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except ToolCallApprovalNotPendingError as exc:
        raise HTTPException(
            status_code=409, detail="This approval was already decided or has expired"
        ) from exc
    except NotAnApproverError as exc:
        raise HTTPException(
            status_code=403, detail="You are not an approver of this tool call"
        ) from exc
    return _response(
        repository_factory,
        decided,
        workspace_slug=await _slug(repository_factory),
        hint=await _tool_hint(repository_factory, decided),
    )
