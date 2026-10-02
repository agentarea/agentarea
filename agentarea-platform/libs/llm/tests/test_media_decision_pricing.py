"""Media and decision costs are converted to the billing currency once, where the call returns.

Budgets and task totals are in the billing currency; a provider USD amount added
to them unconverted would sum RUB and USD into one total.
"""

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_llm.application.decision_service import DecisionService
from agentarea_llm.application.media_generation_service import MediaGenerationService
from agentarea_llm.domain.media import VideoJobStatus
from agentarea_llm.infrastructure.model_clients import (
    DecisionResult,
    GeneratedMedia,
    ModelEndpoint,
    SubmittedVideo,
    VideoStatus,
)

INSTANCE = str(uuid4())


class _Rubles:
    """100 RUB per provider USD; records what it was asked."""

    def __init__(self):
        self.calls: list[dict] = []

    def currency(self) -> str:
        return "RUB"

    async def price_llm_call(self, **call) -> Decimal:
        self.calls.append(call)
        return call["provider_cost_usd"] * 100


def _endpoint(managed_by=None) -> ModelEndpoint:
    return ModelEndpoint(
        instance_id=INSTANCE,
        provider_type="openrouter",
        model_name="m",
        api_key="k",
        endpoint_url=None,
        managed_by=managed_by,
        input_cost_per_token=None,
        output_cost_per_token=None,
    )


class _Models:
    def __init__(self, managed_by=None):
        self.managed_by = managed_by

    async def image_model(self, instance_id):
        async def generate(prompt, size=None):
            return GeneratedMedia(content=b"png", media_type="image/png", cost_usd=Decimal("0.04"))

        return SimpleNamespace(endpoint=_endpoint(self.managed_by), generate=generate)

    async def video_model(self, instance_id):
        async def submit(prompt, **options):
            return SubmittedVideo(provider_job_id="p", status=VideoJobStatus.PENDING)

        async def status(provider_job_id):
            return VideoStatus(status=VideoJobStatus.COMPLETED, cost_usd=Decimal("1.5"), error=None)

        async def content(provider_job_id, index=0):
            return GeneratedMedia(content=b"mp4", media_type="video/mp4", cost_usd=None)

        return SimpleNamespace(
            endpoint=_endpoint(self.managed_by), submit=submit, status=status, content=content
        )

    async def decision_model(self, instance_id):
        async def evaluate(state, questions):
            return DecisionResult(
                answers={"q": {"type": "noul", "noul": 0.9}},
                cost_usd=Decimal("0.0004"),
                input_tokens=100,
                output_tokens=2,
            )

        return SimpleNamespace(endpoint=_endpoint(self.managed_by), evaluate=evaluate)


class _Jobs:
    def __init__(self):
        self.rows: dict = {}

    async def create(self, **kwargs):
        row = SimpleNamespace(id=uuid4(), file_path=None, error=None, **kwargs)
        self.rows[row.id] = row
        return row

    async def get_for_task(self, job_id, task_id):
        return self.rows.get(job_id)

    async def update(self, id, **kwargs):
        return self.rows[id]


def _media(pricing, managed_by=None) -> MediaGenerationService:
    return MediaGenerationService(
        models=_Models(managed_by),  # type: ignore[arg-type]
        jobs=_Jobs(),  # type: ignore[arg-type]
        task_id="t",
        image_model_id=INSTANCE,
        video_model_id=INSTANCE,
        call_ref="t:call-1",
        pricing=pricing,
    )


async def test_an_image_carries_the_billing_currency_amount():
    pricing = _Rubles()

    image = await _media(pricing, managed_by=MANAGED_BY_PLATFORM).generate_image("a cat")

    assert image.cost == Decimal("4.00")
    assert image.currency == "RUB"
    assert pricing.calls == [
        {
            "model_instance_id": INSTANCE,
            "platform_funded": True,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "provider_cost_usd": Decimal("0.04"),
        }
    ]


async def test_a_finished_video_carries_the_billing_currency_amount():
    pricing = _Rubles()
    media = _media(pricing)
    job_id = (await media.submit_video("waves")).job_id

    check = await media.check_video(job_id)

    assert check.cost_usd == Decimal("1.5")
    assert check.cost == Decimal("150.0")
    assert [call["platform_funded"] for call in pricing.calls] == [False]
    assert UUID(job_id)


async def test_a_decision_carries_the_billing_currency_amount_and_its_tokens():
    pricing = _Rubles()
    service = DecisionService(
        models=_Models(MANAGED_BY_PLATFORM),  # type: ignore[arg-type]
        model_id=INSTANCE,
        pricing=pricing,
    )

    outcome = await service.evaluate("state", {"q": {"type": "noul", "instructions": "?"}})

    assert outcome.cost == Decimal("0.04")
    assert outcome.answers == {"q": {"type": "noul", "noul": 0.9}}
    assert pricing.calls[0]["prompt_tokens"] == 100
    assert pricing.calls[0]["completion_tokens"] == 2
