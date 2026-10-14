"""A media call's cost is what billing says it is, once, where the call returns.

Budgets and task totals are in the deployment currency; a provider USD amount added
to them unconverted would sum RUB and USD into one total. On the platform's
credentials billing prices the call; on the customer's own it converts the cost.
"""

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_llm.application.media_generation_service import MediaGenerationService
from agentarea_llm.domain.media import VideoJobStatus
from agentarea_llm.infrastructure.model_clients import (
    GeneratedMedia,
    ModelEndpoint,
    SubmittedVideo,
    VideoStatus,
)

INSTANCE = str(uuid4())


class _Rubles:
    """Billing in RUB: 100 per provider USD on the customer's key, 150 on ours."""

    def __init__(self):
        self.calls: list = []

    def currency(self) -> str:
        return "RUB"

    async def authorize(self, **request):
        raise AssertionError("a media call is priced afterwards, not held")

    async def capture(self, **request):
        raise AssertionError("no hold to capture")

    async def void(self, *, hold_id):
        raise AssertionError("no hold to void")

    async def quote(self, lines):
        self.calls.extend(lines)
        return [
            SimpleNamespace(
                amount=line.vendor_cost * (150 if line.payer == "platform" else 100), code="ok"
            )
            for line in lines
        ]


@pytest.fixture
def pricing(monkeypatch):
    from agentarea_common.extensions import tool_billing
    from agentarea_common.extensions.registry import ExtensionRegistry

    billing = _Rubles()
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "RUB")
    monkeypatch.setattr(ExtensionRegistry, "_factories", {"tool_billing": lambda: billing})
    tool_billing.get_tool_billing.cache_clear()
    yield billing
    tool_billing.get_tool_billing.cache_clear()


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


def _media(managed_by=None) -> MediaGenerationService:
    return MediaGenerationService(
        models=_Models(managed_by),  # type: ignore[arg-type]
        jobs=_Jobs(),  # type: ignore[arg-type]
        task_id="t",
        image_model_id=INSTANCE,
        video_model_id=INSTANCE,
        call_ref="t:call-1",
    )


async def test_an_image_on_our_key_carries_billings_price(pricing):
    image = await _media(managed_by=MANAGED_BY_PLATFORM).generate_image("a cat")

    assert image.cost == Decimal("6.00")
    assert image.currency == "RUB"
    [line] = pricing.calls
    assert (line.payer, line.kind, line.tool, line.vendor_cost) == (
        "platform",
        "model",
        INSTANCE,
        Decimal("0.04"),
    )


async def test_a_finished_video_on_the_customers_key_is_converted(pricing):
    media = _media()
    job_id = (await media.submit_video("waves")).job_id

    check = await media.check_video(job_id)

    assert check.cost_usd == Decimal("1.5")
    assert check.cost == Decimal("150.0")
    assert [line.payer for line in pricing.calls] == ["workspace"]
    assert UUID(job_id)
