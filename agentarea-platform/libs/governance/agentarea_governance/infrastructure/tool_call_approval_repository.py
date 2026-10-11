"""Repository for tool-call approvals, scoped to the caller's workspace.

A call is matched by who made it, the connection, the tool and the arguments
hash. State moves by conditional UPDATEs, so a decision lands only on a pending
row and an approval is consumed by exactly one of two concurrent retries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.tool_call_approvals import (
    APPROVED_TTL,
    LAPSING_STATUSES,
    PENDING_TTL,
    ToolCallApproval,
    ToolCallApprovalStatus,
    ToolCallRequest,
    as_utc,
)
from .orm import ToolCallApprovalORM

_ORM = ToolCallApprovalORM
_STATUS = ToolCallApprovalStatus


def _uuid(value: UUID | str | None) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _to_approval(row: ToolCallApprovalORM, now: datetime) -> ToolCallApproval:
    expires_at = as_utc(row.expires_at)
    status = _STATUS(row.status)
    if status in LAPSING_STATUSES and expires_at <= now:
        status = _STATUS.EXPIRED
    return ToolCallApproval(
        id=str(row.id),
        workspace_id=row.workspace_id,
        requested_by=row.created_by,
        client_id=row.client_id,
        client_name=row.client_name,
        mcp_instance_id=str(row.mcp_instance_id) if row.mcp_instance_id else None,
        connector=row.connector,
        tool=row.tool,
        policy_name=row.policy_name,
        arguments=row.arguments,
        arguments_hash=row.arguments_hash,
        status=status,
        reason=row.reason,
        approvers=list(row.approvers or []),
        decided_by=row.decided_by,
        decided_at=as_utc(row.decided_at) if row.decided_at else None,
        comment=row.comment,
        expires_at=expires_at,
        # BaseModel stamps created_at with the naive local clock.
        created_at=row.created_at.astimezone(UTC),
    )


class ToolCallApprovalRepository:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    def _in_workspace(self) -> ColumnElement[bool]:
        return _ORM.workspace_id == self.user_context.workspace_id

    def _same_call(
        self, mcp_instance_id: str | None, tool: str, arguments_hash: str
    ) -> ColumnElement[bool]:
        instance = _uuid(mcp_instance_id)
        return and_(
            self._in_workspace(),
            _ORM.created_by == self.user_context.user_id,
            _ORM.mcp_instance_id.is_(None)
            if instance is None
            else _ORM.mcp_instance_id == instance,
            _ORM.tool == tool,
            _ORM.arguments_hash == arguments_hash,
        )

    async def _update_returning(self, stmt: Any, now: datetime) -> ToolCallApproval | None:
        result = await self.session.execute(
            stmt.returning(_ORM).execution_options(populate_existing=True)
        )
        row = result.scalars().first()
        return _to_approval(row, now) if row is not None else None

    async def expire_lapsed(
        self, *, mcp_instance_id: str | None, tool: str, arguments_hash: str, now: datetime
    ) -> None:
        """Mark this call's pending and approved rows past their deadline expired."""
        await self.session.execute(
            update(_ORM)
            .where(
                self._same_call(mcp_instance_id, tool, arguments_hash),
                _ORM.status.in_([s.value for s in LAPSING_STATUSES]),
                _ORM.expires_at <= now,
            )
            .values(status=_STATUS.EXPIRED.value)
            .execution_options(synchronize_session=False)
        )

    async def consume_approved(
        self, *, mcp_instance_id: str | None, tool: str, arguments_hash: str, now: datetime
    ) -> ToolCallApproval | None:
        """Use one live approval of this call; None when there is none to use.

        The status is rechecked by the UPDATE itself, so of two concurrent
        retries only the first to write gets the row.
        """
        usable = and_(_ORM.status == _STATUS.APPROVED.value, _ORM.expires_at > now)
        target = (
            select(_ORM.id)
            .where(self._same_call(mcp_instance_id, tool, arguments_hash), usable)
            .order_by(_ORM.decided_at)
            .limit(1)
            .scalar_subquery()
        )
        return await self._update_returning(
            update(_ORM)
            .where(_ORM.id == target, self._in_workspace(), usable)
            .values(status=_STATUS.CONSUMED.value),
            now,
        )

    async def find_live(
        self,
        status: ToolCallApprovalStatus,
        *,
        mcp_instance_id: str | None,
        tool: str,
        arguments_hash: str,
        now: datetime,
    ) -> ToolCallApproval | None:
        """The newest row of this call in ``status`` whose deadline has not passed."""
        row = (
            await self.session.scalars(
                select(_ORM)
                .where(
                    self._same_call(mcp_instance_id, tool, arguments_hash),
                    _ORM.status == status.value,
                    _ORM.expires_at > now,
                )
                .order_by(_ORM.created_at.desc())
                .limit(1)
            )
        ).first()
        return _to_approval(row, now) if row is not None else None

    async def create_pending(
        self, request: ToolCallRequest, arguments_hash: str, now: datetime
    ) -> ToolCallApproval | None:
        """Record the call as pending; None when a concurrent retry recorded it first."""
        row = _ORM(
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
            client_id=request.client_id,
            client_name=request.client_name,
            mcp_instance_id=_uuid(request.mcp_instance_id),
            connector=request.connector,
            tool=request.tool,
            policy_name=request.policy_name,
            arguments=request.arguments,
            arguments_hash=arguments_hash,
            status=_STATUS.PENDING.value,
            reason=request.reason,
            approvers=list(request.approvers),
            expires_at=now + PENDING_TTL,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError:
            return None
        return _to_approval(row, now)

    async def get(self, approval_id: UUID | str, now: datetime) -> ToolCallApproval | None:
        approval_uuid = _uuid(approval_id)
        if approval_uuid is None:
            return None
        row = (
            await self.session.scalars(
                select(_ORM).where(self._in_workspace(), _ORM.id == approval_uuid)
            )
        ).first()
        return _to_approval(row, now) if row is not None else None

    def _status_filter(self, status: ToolCallApprovalStatus, now: datetime) -> ColumnElement[bool]:
        if status in LAPSING_STATUSES:
            return and_(_ORM.status == status.value, _ORM.expires_at > now)
        if status is _STATUS.EXPIRED:
            return or_(
                _ORM.status == status.value,
                and_(
                    _ORM.status.in_([s.value for s in LAPSING_STATUSES]),
                    _ORM.expires_at <= now,
                ),
            )
        return _ORM.status == status.value

    async def list(
        self,
        *,
        status: ToolCallApprovalStatus | None,
        now: datetime,
        limit: int,
        offset: int,
    ) -> tuple[list[ToolCallApproval], int]:
        conditions = [self._in_workspace()]
        if status is not None:
            conditions.append(self._status_filter(status, now))
        rows = (
            await self.session.scalars(
                select(_ORM)
                .where(*conditions)
                .order_by(_ORM.created_at.desc(), _ORM.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        total = await self.session.scalar(select(func.count()).select_from(_ORM).where(*conditions))
        return [_to_approval(row, now) for row in rows], int(total or 0)

    async def decide(
        self,
        approval_id: UUID | str,
        *,
        approved: bool,
        comment: str | None,
        now: datetime,
    ) -> ToolCallApproval | None:
        """Record the caller's decision on a pending, unexpired row; None otherwise.

        An approval is usable for ``APPROVED_TTL``. A rejection keeps the
        pending deadline: until then the same call is answered with it.
        """
        values: dict[str, Any] = {
            "status": (_STATUS.APPROVED if approved else _STATUS.REJECTED).value,
            "decided_by": self.user_context.user_id,
            "decided_at": now,
            "comment": comment,
        }
        if approved:
            values["expires_at"] = now + APPROVED_TTL
        return await self._update_returning(
            update(_ORM)
            .where(
                self._in_workspace(),
                _ORM.id == _uuid(approval_id),
                _ORM.status == _STATUS.PENDING.value,
                _ORM.expires_at > now,
            )
            .values(**values),
            now,
        )
