from datetime import UTC, datetime
from uuid import uuid4

from agentarea_api.api.v1.triggers import TriggerResponse
from agentarea_streams.domain.models import TriggerBinding
from agentarea_triggers.domain.models import WebhookTrigger


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


def test_a_stopped_trigger_without_an_owner_problem_is_inactive():
    response = TriggerResponse.from_domain_model(_trigger(is_active=False))
    assert response.status == "inactive"
    assert response.needs_new_owner_at is None
    assert response.stream_id is None
