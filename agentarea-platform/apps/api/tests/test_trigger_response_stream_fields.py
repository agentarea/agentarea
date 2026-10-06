from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from agentarea_api.api.v1.triggers import TriggerResponse, _has_credentials, _webhook_signing
from agentarea_streams.domain.models import TriggerBinding
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import Trigger, WebhookTrigger
from agentarea_triggers.infrastructure.orm import TriggerORM


def _trigger(**kw):
    return WebhookTrigger(
        name="gh",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="w",
        webhook_id="abc1234567890xyz",
        webhook_type="github",
        **kw,
    )


def test_the_webhook_url_and_last_event_come_from_the_stream(monkeypatch):
    monkeypatch.setattr(
        "agentarea_api.api.v1.triggers.public_webhook_url",
        lambda wid: f"https://api.example/webhooks/{wid}",
    )
    stream_id, last = uuid4(), datetime(2026, 10, 6, 9, 30, tzinfo=UTC)
    response = TriggerResponse.from_domain_model(
        _trigger(),
        binding=TriggerBinding(
            stream_id=stream_id,
            event_filter={"kinds": ["push"]},
            webhook_id="abc1234567890xyz",
            last_event_at=last,
        ),
    )
    assert response.webhook_url == "https://api.example/webhooks/abc1234567890xyz"
    assert response.stream_id == stream_id
    assert response.event_filter == {"kinds": ["push"]}
    assert response.last_event_at == last
    assert response.status == "active"


def test_a_trigger_whose_configurer_left_says_so():
    response = TriggerResponse.from_domain_model(
        _trigger(
            is_active=False,
            needs_new_owner_at=datetime(2026, 10, 6, tzinfo=UTC).replace(tzinfo=None),
        )
    )
    assert response.status == "needs_owner"
    assert response.webhook_url is None


def test_an_enabled_trigger_is_active_whatever_its_owner_stamp_says():
    response = TriggerResponse.from_domain_model(
        _trigger(
            is_active=True,
            needs_new_owner_at=datetime(2026, 10, 6, tzinfo=UTC).replace(tzinfo=None),
        )
    )
    assert response.status == "active"


def test_a_stopped_trigger_without_an_owner_problem_is_inactive():
    response = TriggerResponse.from_domain_model(_trigger(is_active=False))
    assert response.status == "inactive"
    assert response.needs_new_owner_at is None
    assert response.stream_id is None


def _listed_stream_row() -> TriggerORM:
    """A stream trigger as the list reads it: an ORM row, here one stored before the fix."""
    return TriggerORM(
        id=uuid4(),
        name="orders listener",
        description="",
        agent_id=uuid4(),
        trigger_type="stream",
        is_active=True,
        task_parameters={},
        conditions={},
        created_by="u",
        workspace_id="w",
        failure_threshold=5,
        consecutive_failures=0,
        webhook_type="generic",
        allowed_methods=["POST"],
        validation_rules={},
        created_at=datetime(2026, 10, 6),
        updated_at=datetime(2026, 10, 6),
    )


def _stream_detail(row: TriggerORM) -> Trigger:
    return Trigger(
        id=row.id,
        name=row.name,
        agent_id=row.agent_id,
        created_by="u",
        workspace_id="w",
        trigger_type=TriggerType.STREAM,
    )


async def test_a_listed_stream_trigger_has_no_webhook_fields_and_matches_its_detail():
    row = _listed_stream_row()
    secrets = AsyncMock()
    secrets.has_secret.return_value = False

    listed = TriggerResponse.from_domain_model(
        row,
        has_channel_credentials=await _has_credentials(secrets, row, row.id),
        webhook_signing=await _webhook_signing(secrets, row),
    )
    detail = TriggerResponse.from_domain_model(_stream_detail(row))

    webhook_fields = (
        "webhook_type",
        "webhook_id",
        "allowed_methods",
        "validation_rules",
        "webhook_config",
        "webhook_signing",
        "signature_scheme",
    )
    assert {f: getattr(listed, f) for f in webhook_fields} == dict.fromkeys(webhook_fields)
    assert {f: getattr(detail, f) for f in webhook_fields} == dict.fromkeys(webhook_fields)
    secrets.has_secret.assert_awaited_once_with(f"channel_cred:generic:{row.id}")


def test_a_listed_webhook_trigger_still_shows_its_channel():
    row = _listed_stream_row()
    row.trigger_type = "webhook"
    row.webhook_id = "abc1234567890xyz"
    row.webhook_type = "github"
    assert TriggerResponse.from_domain_model(row).webhook_type == "github"
