"""Application service for tool-call approvals: the gate a client call passes, and the decision."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from agentarea_common.audit import AuditService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.tool_authorization import caller_can_approve
from agentarea_common.base.repository_factory import RepositoryFactory

from ..domain.tool_call_approvals import (
    GateOutcome,
    GateVerdict,
    NotAnApproverError,
    ToolCallApproval,
    ToolCallApprovalNotFoundError,
    ToolCallApprovalNotPendingError,
    ToolCallApprovalStatus,
    ToolCallRequest,
    arguments_hash,
)
from ..infrastructure.tool_call_approval_repository import ToolCallApprovalRepository


class ToolCallApprovalService:
    """Holds a client's approval-gated call until a person decides, then lets it run once.

    The caller's workspace and user come from the context the service was built
    with: an approval matches only the person whose client made the call.
    """

    def __init__(self, repository_factory: RepositoryFactory):
        self.repository_factory = repository_factory
        self._repository = repository_factory.create_repository(ToolCallApprovalRepository)

    @property
    def _user_context(self) -> UserContext:
        return self.repository_factory.user_context

    @staticmethod
    def may_decide(approval: ToolCallApproval, user_id: str) -> bool:
        """Whether ``user_id`` may decide: a named approver, or anyone when none is named."""
        return caller_can_approve(approval.approvers, user_id)

    async def gate(self, request: ToolCallRequest) -> GateOutcome:
        """Run with a live approval of this exact call, else answer with its approval.

        A rejected call is answered with the rejection until its deadline; an
        open request is reused; otherwise a new one is recorded.
        """
        now = datetime.now(UTC)
        call = {
            "mcp_instance_id": request.mcp_instance_id,
            "tool": request.tool,
            "arguments_hash": arguments_hash(request.arguments),
            "now": now,
        }
        await self._repository.expire_lapsed(**call)
        consumed = await self._repository.consume_approved(**call)
        if consumed is not None:
            return GateOutcome(GateVerdict.RUN, consumed)
        rejected = await self._repository.find_live(ToolCallApprovalStatus.REJECTED, **call)
        if rejected is not None:
            return GateOutcome(GateVerdict.REJECTED, rejected)
        pending = (
            await self._repository.find_live(ToolCallApprovalStatus.PENDING, **call)
            or await self._repository.create_pending(request, call["arguments_hash"], now)
            or await self._repository.find_live(ToolCallApprovalStatus.PENDING, **call)
        )
        if pending is None:
            raise RuntimeError(
                f"No pending approval of {request.tool} could be recorded or found for "
                f"{self._user_context.user_id}"
            )
        return GateOutcome(GateVerdict.PENDING, pending)

    async def get(self, approval_id: UUID | str) -> ToolCallApproval | None:
        return await self._repository.get(approval_id, datetime.now(UTC))

    async def list(
        self,
        *,
        status: ToolCallApprovalStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ToolCallApproval], int]:
        return await self._repository.list(
            status=status, now=datetime.now(UTC), limit=limit, offset=offset
        )

    async def decide(
        self, approval_id: UUID | str, *, approved: bool, comment: str | None = None
    ) -> ToolCallApproval:
        """Approve or reject a pending call, as the context's user, and audit it."""
        now = datetime.now(UTC)
        approval = await self._repository.get(approval_id, now)
        if approval is None:
            raise ToolCallApprovalNotFoundError(str(approval_id))
        if approval.status is not ToolCallApprovalStatus.PENDING:
            raise ToolCallApprovalNotPendingError(approval.status.value)
        if not self.may_decide(approval, self._user_context.user_id):
            raise NotAnApproverError(self._user_context.user_id)
        decided = await self._repository.decide(
            approval.id, approved=approved, comment=comment, now=now
        )
        if decided is None:
            raise ToolCallApprovalNotPendingError("decided concurrently")
        await AuditService(self.repository_factory.session, self._user_context).record(
            "tool_call_approval.approved" if approved else "tool_call_approval.rejected",
            "tool_call_approval",
            decided.id,
            event_metadata={
                "tool": decided.tool,
                "connector": decided.connector,
                "mcp_instance_id": decided.mcp_instance_id,
                "requested_by": decided.requested_by,
                "client_id": decided.client_id,
                "comment": decided.comment,
            },
        )
        return decided
