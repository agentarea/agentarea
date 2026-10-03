"""A person's verdict on a run. People only: an API key cannot rate."""

from uuid import UUID

from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import UserContextDep, get_principal
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.config.database import get_db_session
from agentarea_evals.feedback.service import FeedbackService, UnknownRunError
from agentarea_evals.schemas import FeedbackCreate, FeedbackResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/tasks/{task_id}/feedback", tags=["run-feedback"])

_MEMBER = unrestricted("workspace member; the workspace-scoped repository is the boundary")


@router.get("", response_model=list[FeedbackResponse], dependencies=[_MEMBER])
async def list_feedback(
    task_id: UUID, user_context: UserContextDep, session: AsyncSession = Depends(get_db_session)
):
    feedback = await FeedbackService(session, user_context).list_for_task(task_id)
    return [FeedbackResponse.build(f) for f in feedback]


@router.put("", response_model=FeedbackResponse, dependencies=[_MEMBER])
async def rate_run(
    task_id: UUID,
    payload: FeedbackCreate,
    user_context: UserContextDep,
    principal: UserPrincipal = Depends(get_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Rate a run; rating it again replaces your previous verdict.

    Ratings feed revision stats and experiment guardrails, so an agent or an
    integration holding an API key must not be able to write one.
    """
    if principal.api_key_id is not None:
        raise HTTPException(status_code=403, detail="Runs are rated by people; sign in to rate")
    try:
        feedback = await FeedbackService(session, user_context).rate(
            task_id, payload.rating, comment=payload.comment, event_id=payload.event_id
        )
    except UnknownRunError as error:
        raise HTTPException(status_code=404, detail="Run not found") from error
    return FeedbackResponse.build(feedback)
