"""Inbound email: webhook payload -> trigger data -> channel_origin."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import WebhookType
from agentarea_triggers.domain.models import WebhookTrigger
from agentarea_triggers.trigger_service import TriggerService
from agentarea_triggers.webhook_manager import DefaultWebhookManager, WebhookRequestData


@pytest.fixture
def webhook_manager():
    return DefaultWebhookManager(
        execution_callback=AsyncMock(), event_broker=None, base_url="/webhooks"
    )


@pytest.fixture
def trigger_service():
    factory = AsyncMock()
    factory.create_repository.return_value = AsyncMock()
    return TriggerService(repository_factory=factory, event_broker=AsyncMock())


def email_trigger(**kwargs) -> WebhookTrigger:
    return WebhookTrigger(
        name="Agent inbox",
        agent_id=uuid4(),
        created_by="user1",
        webhook_id="wh_mail_1",
        webhook_type=WebhookType.EMAIL,
        **kwargs,
    )


def request_with(body) -> WebhookRequestData:
    return WebhookRequestData(
        webhook_id="wh_mail_1",
        method="POST",
        headers={"content-type": "application/json"},
        body=body,
        query_params={},
    )


class TestParseEmailWebhook:
    async def test_canonical_payload_becomes_trigger_data(self, webhook_manager):
        data = await webhook_manager._parse_webhook_data(
            email_trigger(),
            request_with(
                {
                    "from": "alice@example.com",
                    "to": "agent@agentarea.test",
                    "subject": "Deploy failed",
                    "text": "please look",
                    "message_id": "<m1@example.com>",
                }
            ),
        )

        assert data["event_type"] == "message_received"
        assert data["from"] == "alice@example.com"
        assert data["subject"] == "Deploy failed"
        assert data["text"] == "please look"
        assert data["message_id"] == "<m1@example.com>"

    async def test_provider_field_names_are_configuration(self, webhook_manager):
        """A vendor's JSON keys belong in config, never in a branch in our code."""
        trigger = email_trigger(
            webhook_config={
                "field_map": {
                    "from": "From.Address",
                    "text": "Text",
                    "subject": "Subject",
                    "message_id": "ID",
                }
            }
        )

        data = await webhook_manager._parse_webhook_data(
            trigger,
            request_with(
                {
                    "From": {"Name": "Alice", "Address": "alice@example.com"},
                    "Subject": "Deploy failed",
                    "Text": "please look",
                    "ID": "<m1@example.com>",
                }
            ),
        )

        assert data["from"] == "alice@example.com"
        assert data["text"] == "please look"

    async def test_the_raw_payload_is_kept(self, webhook_manager):
        body = {"from": "a@b.test", "text": "hi", "weird_vendor_field": 7}

        data = await webhook_manager._parse_webhook_data(email_trigger(), request_with(body))

        assert data["raw_data"] == body

    async def test_a_payload_that_is_not_an_object_does_not_explode(self, webhook_manager):
        """A malformed POST must not take the webhook endpoint down."""
        data = await webhook_manager._parse_webhook_data(
            email_trigger(), request_with("this is not json")
        )

        assert "parse_error" in data


class TestEmailChannelOrigin:
    def test_builds_a_reply_route_from_parsed_mail(self, trigger_service):
        trigger = email_trigger()
        trigger_data = {
            "from": "alice@example.com",
            "subject": "Deploy failed",
            "message_id": "<m1@example.com>",
            "references": [],
        }

        origin = trigger_service._build_channel_origin(trigger, trigger_data)

        assert origin["type"] == "email"
        assert origin["reply_to"] == "alice@example.com"
        assert origin["subject"] == "Re: Deploy failed"
        assert origin["chat_id"] == "<m1@example.com>"
        assert origin["trigger_id"] == str(trigger.id)

    def test_a_reply_keeps_the_thread_key_of_the_first_message(self, trigger_service):
        trigger = email_trigger()

        first = trigger_service._build_channel_origin(
            trigger,
            {"from": "alice@example.com", "message_id": "<root@x>", "references": []},
        )
        second = trigger_service._build_channel_origin(
            trigger,
            {
                "from": "alice@example.com",
                "message_id": "<second@x>",
                "in_reply_to": "<root@x>",
                "references": ["<root@x>"],
            },
        )

        assert second["chat_id"] == first["chat_id"] == "<root@x>"

    def test_mail_with_no_sender_gets_no_route(self, trigger_service):
        origin = trigger_service._build_channel_origin(
            email_trigger(), {"subject": "x", "message_id": "<m@x>", "references": []}
        )

        assert origin is None
