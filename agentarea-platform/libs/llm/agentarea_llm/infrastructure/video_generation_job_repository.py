from decimal import Decimal
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_llm.domain.media import VideoJobStatus
from agentarea_llm.domain.models import VideoGenerationJob


class VideoGenerationJobRepository(WorkspaceScopedRepository[VideoGenerationJob]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, VideoGenerationJob, user_context)

    async def get_for_task(self, job_id: UUID, task_id: str | None) -> VideoGenerationJob | None:
        """The job, only when this workspace's ``task_id`` submitted it."""
        return await self.find_one_by(id=job_id, task_id=task_id)

    async def record_saved(
        self,
        job_id: UUID,
        file_path: str,
        *,
        cost_usd: Decimal,
        billed_cost: Decimal,
        call_ref: str,
    ) -> bool:
        """Record the finished video and which tool call bills it, once.

        True when ``call_ref`` is the call that bills it: the first to record it,
        or a retry of that call. False for any other call, which must report
        nothing, because the generation is already charged.
        """
        result = await self.session.execute(
            update(VideoGenerationJob)
            .where(
                VideoGenerationJob.id == job_id,
                VideoGenerationJob.workspace_id == self.user_context.workspace_id,
                VideoGenerationJob.file_path.is_(None),
            )
            .values(
                status=VideoJobStatus.COMPLETED,
                file_path=file_path,
                cost_usd=cost_usd,
                billed_cost=billed_cost,
                billed_call_ref=call_ref,
            )
        )
        await self.session.commit()
        if getattr(result, "rowcount", 0):
            return True
        job = await self.get_by_id(job_id)
        return job is not None and job.billed_call_ref == call_ref
