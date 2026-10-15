"""A media call's cost is what billing says it is, once, where the call returns.

Budgets and task totals are in the deployment currency; a provider USD amount added
to them unconverted would sum RUB and USD into one total. On the platform's
credentials billing holds the call before the provider is paid and prices it after;
on the customer's own it converts the cost.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.model_charges import ModelCallRefusedError, require_funding
from agentarea_llm.application.media_generation_service import MediaGenerationService
from agentarea_llm.domain.media import VideoJobStatus
from agentarea_llm.infrastructure.model_clients import (
    GeneratedMedia,
    ModelTarget,
    SubmittedVideo,
    VideoStatus,
)
from agentarea_tasks.model_spend_caps import SpendCapReachedError

INSTANCE = str(uuid4())


class _Rubles:
    """Billing in RUB: 100 per provider USD on the customer's key, 150 on ours."""

    def __init__(self, events: list):
        self.events = events
        self.calls: list = []
        self.authorizations: list = []
        self.voids: list = []

    def currency(self) -> str:
        return "RUB"

    async def authorize(self, **request):
        self.events.append("authorize")
        self.authorizations.append(request)
        return SimpleNamespace(
            allowed=True,
            code="ok",
            reason="",
            hold_id="hold-1",
            amount=request["vendor_cost"] * 150,
            currency="RUB",
            expires_at=None,
        )

    async def capture(self, **request):
        raise AssertionError("the settlement worker captures")

    async def void(self, *, hold_id):
        self.voids.append(hold_id)

    async def quote(self, lines):
        self.calls.extend(lines)
        return [
            SimpleNamespace(
                amount=line.vendor_cost * (150 if line.payer == "platform" else 100), code="ok"
            )
            for line in lines
        ]


@pytest.fixture
def events() -> list:
    return []


@pytest.fixture
def pricing(monkeypatch, events):
    from agentarea_common.extensions import tool_billing
    from agentarea_common.extensions.registry import ExtensionRegistry

    billing = _Rubles(events)
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "RUB")
    monkeypatch.setattr(ExtensionRegistry, "_factories", {"tool_billing": lambda: billing})
    tool_billing.get_tool_billing.cache_clear()
    yield billing
    tool_billing.get_tool_billing.cache_clear()


def _target(instance_id, managed_by, prices) -> ModelTarget:
    return ModelTarget(
        instance_id=str(instance_id),
        provider_type="openrouter",
        model_name="m",
        endpoint_url=None,
        managed_by=managed_by,
        input_cost_per_token=None,
        output_cost_per_token=None,
        **prices,
    )


class _Models:
    def __init__(self, events, managed_by=None, image_cost=Decimal("0.04"), video=None, **prices):
        self.events = events
        self.managed_by = managed_by
        self.image_cost = image_cost
        self.video = video or VideoStatus(
            status=VideoJobStatus.COMPLETED, cost_usd=Decimal("1.5"), error=None
        )
        self.prices = prices

    async def describe(self, instance_id, kind):
        return _target(instance_id, self.managed_by, self.prices)

    async def image_model(self, target, funding):
        require_funding(funding, target.managed_by)

        async def generate(prompt, size=None):
            self.events.append("generate")
            return GeneratedMedia(content=b"png", media_type="image/png", cost_usd=self.image_cost)

        return SimpleNamespace(generate=generate)

    async def video_model(self, target, funding):
        require_funding(funding, target.managed_by)

        async def submit(prompt, **options):
            self.events.append("submit")
            return SubmittedVideo(provider_job_id="p", status=VideoJobStatus.PENDING)

        async def status(provider_job_id):
            return self.video

        async def content(provider_job_id, index=0):
            return GeneratedMedia(content=b"mp4", media_type="video/mp4", cost_usd=None)

        return SimpleNamespace(submit=submit, status=status, content=content)


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
        row = self.rows[id]
        for key, value in kwargs.items():
            setattr(row, key, value)
        return row


def _media(
    models: _Models, jobs: _Jobs | None = None, refuse_at_spend_cap: AsyncMock | None = None
) -> MediaGenerationService:
    return MediaGenerationService(
        models=models,  # type: ignore[arg-type]
        jobs=jobs or _Jobs(),  # type: ignore[arg-type]
        workspace_id="ws-1",
        task_id="t",
        image_model_id=INSTANCE,
        video_model_id=INSTANCE,
        call_ref="t:call-1",
        refuse_at_spend_cap=refuse_at_spend_cap or AsyncMock(),
    )


async def test_an_image_on_our_key_is_held_before_the_provider_and_carries_billings_price(
    pricing, events
):
    models = _Models(
        events, managed_by=MANAGED_BY_PLATFORM, output_cost_per_image=Decimal("0.05")
    )

    image = await _media(models).generate_image("a cat")

    assert events == ["authorize", "generate"]
    [hold] = pricing.authorizations
    assert (hold["workspace_id"], hold["kind"], hold["tool"], hold["vendor_cost"]) == (
        "ws-1",
        "model",
        INSTANCE,
        Decimal("0.05"),
    )
    assert (image.cost, image.currency, image.cost_unknown) == (Decimal("6.00"), "RUB", False)
    assert (image.billing["hold_id"], image.billing["settle"], image.billing["payer"]) == (
        "hold-1",
        "capture",
        "platform",
    )
    [line] = pricing.calls
    assert (line.payer, line.kind, line.tool, line.vendor_cost) == (
        "platform",
        "model",
        INSTANCE,
        Decimal("0.04"),
    )


async def test_media_past_a_monthly_llm_cap_is_refused_before_it_is_held(pricing, events):
    models = _Models(
        events, managed_by=MANAGED_BY_PLATFORM, output_cost_per_image=Decimal("0.05")
    )
    refuse = AsyncMock(side_effect=SpendCapReachedError("Workspace monthly LLM spend cap reached"))
    media = _media(models, refuse_at_spend_cap=refuse)

    with pytest.raises(SpendCapReachedError):
        await media.generate_image("a cat")
    with pytest.raises(SpendCapReachedError):
        await media.submit_video("waves", duration=5)

    assert refuse.await_count == 2
    assert events == []
    assert pricing.authorizations == []


async def test_an_image_on_our_key_without_a_price_is_refused_before_the_provider(
    pricing, events
):
    with pytest.raises(ModelCallRefusedError) as refused:
        await _media(_Models(events, managed_by=MANAGED_BY_PLATFORM)).generate_image("a cat")

    assert refused.value.code == "model_unpriced"
    assert events == []
    assert pricing.calls == []


async def test_an_image_on_our_key_of_unknown_cost_comes_to_the_held_amount(pricing, events):
    models = _Models(
        events,
        managed_by=MANAGED_BY_PLATFORM,
        image_cost=None,
        output_cost_per_image=Decimal("0.05"),
    )

    image = await _media(models).generate_image("a cat")

    assert (image.cost, image.currency, image.cost_unknown) == (Decimal("7.50"), "RUB", True)
    assert (image.billing["hold_id"], image.billing["settle"], image.billing["cost_unknown"]) == (
        "hold-1",
        "capture",
        True,
    )
    assert pricing.calls == []


async def test_an_image_the_provider_did_not_make_releases_its_hold(pricing, events):
    models = _Models(
        events, managed_by=MANAGED_BY_PLATFORM, output_cost_per_image=Decimal("0.05")
    )

    async def broken(target, funding):
        raise RuntimeError("provider down")

    models.image_model = broken  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="provider down"):
        await _media(models).generate_image("a cat")

    assert pricing.voids == ["hold-1"]


def _platform_video(events, status: VideoJobStatus, cost_usd=Decimal("1.5")) -> _Models:
    return _Models(
        events,
        managed_by=MANAGED_BY_PLATFORM,
        video=VideoStatus(status=status, cost_usd=cost_usd, error=None),
        output_cost_per_video_per_second=Decimal("0.1"),
    )


async def test_a_video_on_our_key_is_held_by_its_length_at_submit(pricing, events):
    jobs = _Jobs()

    job_id = (
        await _media(_platform_video(events, VideoJobStatus.PENDING), jobs).submit_video(
            "waves", duration=5
        )
    ).job_id

    assert events == ["authorize", "submit"]
    [hold] = pricing.authorizations
    assert hold["vendor_cost"] == Decimal("0.5")
    funding = jobs.rows[UUID(job_id)].funding
    assert (funding["hold_id"], funding["platform_funded"], funding["held_amount"]) == (
        "hold-1",
        True,
        "75.0",
    )


async def test_a_video_on_our_key_without_a_length_is_refused(pricing, events):
    with pytest.raises(ModelCallRefusedError) as refused:
        await _media(_platform_video(events, VideoJobStatus.PENDING)).submit_video("waves")

    assert refused.value.code == "duration_required"
    assert events == []


async def test_a_failed_video_on_our_key_voids_its_hold(pricing, events):
    jobs = _Jobs()
    media = _media(_platform_video(events, VideoJobStatus.FAILED), jobs)
    job_id = (await media.submit_video("waves", duration=5)).job_id

    check = await media.check_video(job_id)

    assert check.status == VideoJobStatus.FAILED
    assert pricing.voids == ["hold-1"]
    assert pricing.calls == []


async def test_a_finished_video_on_our_key_is_billed_on_its_hold(pricing, events):
    jobs = _Jobs()
    media = _media(_platform_video(events, VideoJobStatus.COMPLETED), jobs)
    job_id = (await media.submit_video("waves", duration=5)).job_id

    check = await media.check_video(job_id)

    assert check.billing is not None
    assert check.billing["hold_id"] == jobs.rows[UUID(job_id)].funding["hold_id"] == "hold-1"
    assert (check.cost, check.currency, check.billing["settle"]) == (
        Decimal("225.0"),
        "RUB",
        "capture",
    )
    assert pricing.voids == []


async def test_a_finished_video_on_the_customers_key_is_converted(pricing, events):
    media = _media(_Models(events))
    job_id = (await media.submit_video("waves")).job_id

    check = await media.check_video(job_id)

    assert check.cost_usd == Decimal("1.5")
    assert check.cost == Decimal("150.0")
    assert pricing.authorizations == []
    assert [line.payer for line in pricing.calls] == ["workspace"]
    assert UUID(job_id)
