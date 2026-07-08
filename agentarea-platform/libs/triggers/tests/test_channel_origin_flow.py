"""Tests for channel_origin flow: trigger → task_parameters."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import WebhookType
from agentarea_triggers.domain.models import CronTrigger, WebhookTrigger
from agentarea_triggers.trigger_service import TriggerService


class TestBuildChannelOrigin:
    """Test _build_channel_origin in TriggerService."""

    @pytest.fixture
    def trigger_service(self):
        mock_factory = AsyncMock()
        mock_factory.create_repository.return_value = AsyncMock()
        return TriggerService(
            repository_factory=mock_factory,
            event_broker=AsyncMock(),
        )

    def test_telegram_webhook_builds_origin(self, trigger_service):
        """Telegram webhook should produce channel_origin with chat_id."""
        trigger = WebhookTrigger(
            name="TG Bot",
            agent_id=uuid4(),
            created_by="user1",
            webhook_id="wh_tg_123",
            webhook_type=WebhookType.TELEGRAM,
        )
        trigger_data = {
            "chat_id": 12345,
            "message_id": 678,
            "username": "johndoe",
            "text": "Hello agent",
        }

        origin = trigger_service._build_channel_origin(trigger, trigger_data)

        assert origin is not None
        assert origin["type"] == "telegram"
        assert origin["chat_id"] == "12345"
        assert origin["message_id"] == 678
        assert origin["presentation"] == "concise"

    def test_slack_webhook_builds_origin(self, trigger_service):
        """Slack webhook should produce channel_origin with channel_id."""
        trigger = WebhookTrigger(
            name="Slack Bot",
            agent_id=uuid4(),
            created_by="user1",
            webhook_id="wh_slack_123",
            webhook_type=WebhookType.SLACK,
        )
        trigger_data = {
            "channel": "C01234",
            "ts": "1234567890.123456",
            "user_name": "jane",
        }

        origin = trigger_service._build_channel_origin(trigger, trigger_data)

        assert origin is not None
        assert origin["type"] == "slack"
        assert origin["channel_id"] == "C01234"
        assert origin["thread_ts"] == "1234567890.123456"

    def test_generic_webhook_no_origin(self, trigger_service):
        """Generic webhook should not produce channel_origin."""
        trigger = WebhookTrigger(
            name="GitHub Hook",
            agent_id=uuid4(),
            created_by="user1",
            webhook_id="wh_gh_123",
            webhook_type=WebhookType.GENERIC,
        )

        origin = trigger_service._build_channel_origin(trigger, {"action": "push"})

        assert origin is None

    def test_cron_trigger_no_origin(self, trigger_service):
        """Plain cron trigger should not produce channel_origin."""
        trigger = CronTrigger(
            name="Daily Job",
            agent_id=uuid4(),
            created_by="user1",
            cron_expression="0 9 * * *",
        )

        origin = trigger_service._build_channel_origin(trigger, {})

        assert origin is None

    def test_extractor_channel_origin_passthrough(self, trigger_service):
        """If trigger_data already has channel_origin (from extractor), use it."""
        trigger = CronTrigger(
            name="Email Poller",
            agent_id=uuid4(),
            created_by="user1",
            cron_expression="*/5 * * * *",
            data_extractor="imap",
        )
        trigger_data = {
            "channel_origin": {
                "type": "email",
                "reply_to": "user@test.com",
                "subject": "Re: Hello",
                "presentation": "summary",
            },
            "extracted_events": [{"type": "email", "body": "Hello"}],
        }

        origin = trigger_service._build_channel_origin(trigger, trigger_data)

        assert origin is not None
        assert origin["type"] == "email"
        assert origin["reply_to"] == "user@test.com"
        assert origin["presentation"] == "summary"


class TestChannelOriginInTaskParams:
    """Test that channel_origin flows into task_parameters."""

    @pytest.fixture
    def trigger_service(self):
        mock_factory = AsyncMock()
        mock_factory.create_repository.return_value = AsyncMock()
        return TriggerService(
            repository_factory=mock_factory,
            event_broker=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_task_params_include_channel_origin(self, trigger_service):
        """Task parameters should include channel_origin for Telegram triggers."""
        trigger = WebhookTrigger(
            name="TG Bot",
            agent_id=uuid4(),
            created_by="user1",
            webhook_id="wh_tg",
            webhook_type=WebhookType.TELEGRAM,
            task_parameters={"instruction": "Respond to the user"},
        )
        trigger_data = {"chat_id": 99999, "text": "Help me"}

        params = await trigger_service._build_task_parameters(trigger, trigger_data)

        assert "channel_origin" in params
        assert params["channel_origin"]["type"] == "telegram"
        assert params["channel_origin"]["chat_id"] == "99999"
        # Original task_parameters preserved
        assert params["instruction"] == "Respond to the user"
        # Trigger metadata preserved
        assert params["trigger_id"] == str(trigger.id)

    @pytest.mark.asyncio
    async def test_task_params_no_origin_for_generic(self, trigger_service):
        """Generic webhooks should not have channel_origin in task params."""
        trigger = WebhookTrigger(
            name="GitHub",
            agent_id=uuid4(),
            created_by="user1",
            webhook_id="wh_gh",
            webhook_type=WebhookType.GENERIC,
        )

        params = await trigger_service._build_task_parameters(trigger, {"action": "push"})

        assert "channel_origin" not in params
