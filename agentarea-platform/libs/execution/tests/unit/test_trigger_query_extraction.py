"""What the agent is asked to do when a trigger fires.

Covers webhook-based (Telegram, Slack, Discord, etc.) and poll-based (extractors)
paths, which reach ``resolve_task_query`` with the events under different keys.

These tests used to carry their own copy of the resolution logic and assert
against that, so they passed no matter what the service did. They call the real
function now.
"""

from uuid import uuid4

import pytest
from agentarea_triggers.domain.models import CronTrigger
from agentarea_triggers.trigger_service import resolve_task_query


def make_trigger(task_parameters: dict | None = None, description: str = "Default trigger"):
    return CronTrigger(
        id=uuid4(),
        name="Nightly",
        description=description,
        agent_id=uuid4(),
        cron_expression="0 9 * * *",
        timezone="UTC",
        created_by="test_user",
        task_parameters=task_parameters or {},
    )


class TestQueryFromWebhookParsedData:
    """Webhook parsers put text at the top level of execution_data."""

    def test_telegram_message_text_extracted(self):
        query = resolve_task_query(
            make_trigger(),
            {
                "webhook_type": "telegram",
                "chat_id": 12345,
                "text": "Привет, помоги мне с задачей",
                "username": "testuser",
            },
        )
        assert query == "Привет, помоги мне с задачей"

    def test_slack_message_text_extracted(self):
        query = resolve_task_query(
            make_trigger(),
            {"webhook_type": "slack", "text": "Deploy the new version", "channel": "C12345"},
        )
        assert query == "Deploy the new version"

    def test_task_text_used_when_the_event_carried_none(self):
        query = resolve_task_query(
            make_trigger({"text": "Run the scheduled report"}),
            {"webhook_type": "generic", "body": {"event": "scheduled"}},
        )
        assert query == "Run the scheduled report"

    def test_multiline_text_preserved(self):
        query = resolve_task_query(make_trigger(), {"text": "Line 1\nLine 2\nLine 3"})
        assert query == "Line 1\nLine 2\nLine 3"


class TestQueryFromPolledEvents:
    """Extractors put what they found under extracted_events."""

    def test_extracted_events_outrank_top_level_text(self):
        query = resolve_task_query(
            make_trigger(),
            {
                "text": "top level text",
                "extracted_events": [{"text": "Event message 1"}, {"text": "Event message 2"}],
            },
        )
        assert query == "Event message 1\nEvent message 2"

    def test_events_outrank_the_task_text(self):
        """What actually arrived beats the standing instruction."""
        query = resolve_task_query(
            make_trigger({"text": "Standing instruction"}),
            {"events": [{"text": "from event"}]},
        )
        assert query == "from event"

    def test_events_without_text_are_ignored(self):
        query = resolve_task_query(
            make_trigger(),
            {
                "text": "fallback from webhook",
                "extracted_events": [{"text": ""}, {"text": None}, {"data": "no text field"}],
            },
        )
        assert query == "fallback from webhook"


class TestNothingToAsk:
    """description explains the automation to a person; it is not an instruction.

    It used to stand in whenever the task text was missing, so a trigger
    described as "every weekday at 06:45 it scores the inbound queue" ran the
    agent against a paraphrase of its own schedule.
    """

    @pytest.mark.parametrize(
        "trigger_data",
        [
            pytest.param({"webhook_type": "generic", "body": {"event": "push"}}, id="no-text"),
            pytest.param({"text": ""}, id="empty-text"),
            pytest.param({"raw_data": {}}, id="cron-fires-with-nothing"),
            pytest.param({"events": [], "channel_origin": {}}, id="manual-run"),
        ],
    )
    def test_a_trigger_with_nothing_to_say_resolves_to_nothing(self, trigger_data):
        assert resolve_task_query(make_trigger(description="Monitor GitHub pushes"), trigger_data) is None

    def test_whitespace_only_task_text_is_not_an_instruction(self):
        assert resolve_task_query(make_trigger({"text": "   "}), {"raw_data": {}}) is None
