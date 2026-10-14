"""Video jobs: the agent holds our id, the provider id stays in the row, billing happens once."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agentarea_common.model_charges import require_funding
from agentarea_llm.application.media_generation_service import (
    MediaGenerationService,
    MediaModelNotConfiguredError,
    VideoJobNotFoundError,
)
from agentarea_llm.domain.media import VideoJobStatus
from agentarea_llm.domain.model_kind import ModelKind
from agentarea_llm.infrastructure.model_clients import (
    GeneratedMedia,
    ModelCallError,
    ModelTarget,
    SubmittedVideo,
    VideoStatus,
)

VIDEO_MODEL = str(uuid4())
IMAGE_MODEL = str(uuid4())
TASK = "task-1"
WORKSPACE = "ws-1"


class _Jobs:
    def __init__(self):
        self.rows: dict[UUID, SimpleNamespace] = {}

    async def create(self, **kwargs):
        row = SimpleNamespace(id=uuid4(), file_path=None, error=None, **kwargs)
        self.rows[row.id] = row
        return row

    async def get_for_task(self, job_id, task_id):
        row = self.rows.get(job_id)
        return row if row is not None and row.task_id == task_id else None

    async def update(self, id, **kwargs):
        row = self.rows[id]
        for key, value in kwargs.items():
            setattr(row, key, value)
        return row

    async def record_saved(self, job_id, file_path, *, cost_usd, billed_cost, billing, call_ref):
        row = self.rows[job_id]
        if row.file_path is not None:
            return row.billed_call_ref == call_ref
        row.file_path, row.cost_usd, row.status = file_path, cost_usd, "completed"
        row.billed_cost, row.billing, row.billed_call_ref = billed_cost, billing, call_ref
        return True


def _target(instance_id) -> ModelTarget:
    return ModelTarget(
        instance_id=str(instance_id),
        provider_type="openrouter",
        model_name="m",
        endpoint_url=None,
        managed_by=None,
        input_cost_per_token=None,
        output_cost_per_token=None,
    )


class _Video:
    def __init__(self, status: VideoStatus):
        self.next_status = status
        self.submitted: list = []

    async def submit(self, prompt, **options):
        self.submitted.append((prompt, options))
        return SubmittedVideo(provider_job_id="gen-vid-provider", status=VideoJobStatus.PENDING)

    async def status(self, provider_job_id):
        assert provider_job_id == "gen-vid-provider"
        return self.next_status

    async def content(self, provider_job_id, index=0):
        return GeneratedMedia(content=b"mp4", media_type="video/mp4", cost_usd=None)


class _Models:
    def __init__(self, video: _Video, image_cost: Decimal | None = Decimal("0.04")):
        self.video = video
        self.video_ids: list = []
        self.image_cost = image_cost

    async def describe(self, instance_id, kind):
        assert kind in (ModelKind.IMAGE, ModelKind.VIDEO)
        return _target(instance_id)

    async def video_model(self, target, funding):
        require_funding(funding, target.managed_by)
        self.video_ids.append(target.instance_id)
        return self.video

    async def image_model(self, target, funding):
        require_funding(funding, target.managed_by)

        async def generate(prompt, size=None):
            return GeneratedMedia(content=b"png", media_type="image/png", cost_usd=self.image_cost)

        return SimpleNamespace(generate=generate)


def _service(video: _Video, jobs: _Jobs, **overrides) -> MediaGenerationService:
    options = {
        "workspace_id": WORKSPACE,
        "task_id": TASK,
        "image_model_id": IMAGE_MODEL,
        "video_model_id": VIDEO_MODEL,
        "call_ref": "task-1:call-1",
    }
    return MediaGenerationService(
        models=_Models(video), jobs=jobs, **{**options, **overrides}
    )


async def test_submit_persists_the_provider_job_and_returns_our_id():
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.PENDING, cost_usd=None, error=None))

    submitted = await _service(video, jobs).submit_video("waves", duration=5)
    job_id = submitted.job_id

    assert submitted.status is VideoJobStatus.PENDING
    row = jobs.rows[UUID(job_id)]
    assert job_id != "gen-vid-provider"
    assert row.provider_job_id == "gen-vid-provider"
    assert row.model_instance_id == UUID(VIDEO_MODEL)
    assert row.task_id == TASK
    assert row.funding == {
        "model_instance_id": VIDEO_MODEL,
        "platform_funded": False,
        "hold_id": None,
        "held_amount": None,
        "held_currency": None,
        "vendor_cost_estimate": None,
    }
    assert video.submitted == [("waves", {"duration": 5, "resolution": None, "aspect_ratio": None})]


async def test_a_running_job_reports_its_status():
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.IN_PROGRESS, cost_usd=None, error=None))
    service = _service(video, jobs)
    job_id = (await service.submit_video("waves")).job_id

    check = await service.check_video(job_id)

    assert check.status == "in_progress"
    assert check.video is None
    assert jobs.rows[UUID(job_id)].status == "in_progress"


async def test_a_finished_video_is_billed_to_exactly_one_tool_call():
    """The invariant: a finished video's cost is reported by one tool call only.

    That call is the first to save it. Every retry of that same call (same
    ``call_ref``) reports the cost again, because an attempt whose result was lost
    after the save committed would otherwise report nothing; the workflow keeps a
    single result per call, so a retried call is still counted once. Any other
    call reports no cost.
    """
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.COMPLETED, cost_usd=Decimal("1.5"), error=None))
    service = _service(video, jobs)
    job_id = (await service.submit_video("waves")).job_id

    check = await service.check_video(job_id)
    assert check.video is not None and check.video.content == b"mp4"
    assert (check.cost_usd, check.cost, check.currency) == (Decimal("1.5"), Decimal("1.5"), "USD")
    assert check.billing is not None and check.billing["payer"] == "workspace"

    def save(media):
        return media.record_video_saved(
            job_id, "media/v.mp4", check.cost_usd, check.cost, check.billing
        )

    assert await save(service)

    retried = await service.check_video(job_id)
    assert (retried.file_path, retried.cost, retried.billing) == (
        "media/v.mp4",
        Decimal("1.5"),
        check.billing,
    )
    assert await save(service)

    other_call = _service(video, jobs, call_ref="task-1:call-2")
    later = await other_call.check_video(job_id)
    assert (later.file_path, later.cost, later.billing) == ("media/v.mp4", None, None)
    assert not await save(other_call)


async def test_a_finished_job_without_a_cost_is_delivered_with_its_cost_unknown():
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.COMPLETED, cost_usd=None, error=None))
    service = _service(video, jobs)
    job_id = (await service.submit_video("waves")).job_id

    check = await service.check_video(job_id)

    assert check.video is not None and check.video.content == b"mp4"
    assert (check.cost_usd, check.cost, check.cost_unknown) == (None, Decimal(0), True)
    assert check.billing is not None and check.billing["cost_unknown"] is True
    assert await service.record_video_saved(
        job_id, "media/v.mp4", None, check.cost, check.billing
    )


async def test_an_image_without_a_cost_is_delivered_with_its_cost_unknown():
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.PENDING, cost_usd=None, error=None))
    service = MediaGenerationService(
        models=_Models(video, image_cost=None),  # type: ignore[arg-type]
        jobs=jobs,  # type: ignore[arg-type]
        workspace_id=WORKSPACE,
        task_id=TASK,
        image_model_id=IMAGE_MODEL,
        video_model_id=VIDEO_MODEL,
        call_ref="task-1:call-1",
    )

    image = await service.generate_image("a cat")

    assert image.content == b"png"
    assert (image.cost, image.currency, image.cost_unknown) == (Decimal(0), "USD", True)
    assert image.billing["cost_unknown"] is True


async def test_a_failed_job_keeps_its_error():
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.FAILED, cost_usd=None, error="moderated"))
    service = _service(video, jobs)
    job_id = (await service.submit_video("waves")).job_id

    check = await service.check_video(job_id)

    assert (check.status, check.error) == ("failed", "moderated")
    assert jobs.rows[UUID(job_id)].error == "moderated"


async def test_a_job_submitted_without_its_funding_cannot_be_checked():
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.COMPLETED, cost_usd=None, error=None))
    service = _service(video, jobs)
    job_id = (await service.submit_video("waves")).job_id
    jobs.rows[UUID(job_id)].funding = None

    with pytest.raises(ModelCallError, match="funding"):
        await service.check_video(job_id)
    assert service._models.video_ids == [VIDEO_MODEL]


async def test_a_job_polls_the_model_that_submitted_it():
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.PENDING, cost_usd=None, error=None))
    job_id = (await _service(video, jobs).submit_video("waves")).job_id
    other = _service(video, jobs, video_model_id=str(uuid4()))

    await other.check_video(job_id)

    assert other._models.video_ids == [VIDEO_MODEL]


async def test_another_tasks_job_is_not_found():
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.PENDING, cost_usd=None, error=None))
    job_id = (await _service(video, jobs).submit_video("waves")).job_id

    with pytest.raises(VideoJobNotFoundError):
        await _service(video, jobs, task_id="another-task").check_video(job_id)


async def test_a_medium_without_a_model_is_refused():
    jobs, video = _Jobs(), _Video(VideoStatus(status=VideoJobStatus.PENDING, cost_usd=None, error=None))

    with pytest.raises(MediaModelNotConfiguredError, match="video"):
        await _service(video, jobs, video_model_id=None).submit_video("waves")
    with pytest.raises(MediaModelNotConfiguredError, match="image"):
        await _service(video, jobs, image_model_id=None).generate_image("a cat")
