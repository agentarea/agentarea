from datetime import UTC, datetime
from uuid import uuid4

from agentarea_api.api.v1.triggers import TriggerResponse
from agentarea_streams.domain.models import TriggerBinding
from agentarea_triggers.domain.models import CronTrigger, StreamTrigger, TriggerSession


def _trigger(**kw):
    return StreamTrigger(
        name="gh",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="w",
        **kw,
    )


def test_the_stream_and_last_event_come_from_the_binding():
    stream_id, last = uuid4(), datetime(2026, 10, 6, 9, 30, tzinfo=UTC)
    response = TriggerResponse.from_domain_model(
        _trigger(),
        binding=TriggerBinding(
            stream_id=stream_id,
            event_filter={"kinds": ["push"]},
            last_event_at=last,
        ),
    )
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


def test_a_stream_trigger_shows_its_session():
    session = TriggerSession.model_validate({"continue": True, "idle_timeout": "30m"})
    response = TriggerResponse.from_domain_model(_trigger(session=session))
    assert response.session == session
    assert response.trigger_type == "stream"


def test_a_cron_trigger_has_no_session():
    cron = CronTrigger(
        name="daily",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="w",
        cron_expression="0 9 * * *",
    )
    response = TriggerResponse.from_domain_model(cron)
    assert response.session is None
    assert response.cron_expression == "0 9 * * *"


def test_a_stream_trigger_shows_its_batch_window():
    from agentarea_triggers.domain.models import TriggerBatchWindow

    batch = TriggerBatchWindow(window="60s", max_events=3)
    response = TriggerResponse.from_domain_model(_trigger(batch=batch))
    assert response.batch == batch
    assert TriggerResponse.from_domain_model(_trigger()).batch is None
