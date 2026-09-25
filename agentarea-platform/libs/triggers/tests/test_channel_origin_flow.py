"""Tests for channel_origin flow: trigger → task_parameters."""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_triggers.channels.adapters import _resolve_token
from agentarea_triggers.domain.enums import WebhookType
from agentarea_triggers.domain.models import CronTrigger, WebhookTrigger
from agentarea_triggers.trigger_service import TriggerService

from .conftest import make_trigger_repository_factory


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


class TestSuppliedChannelOriginCannotBorrowAnotherTrigger:
    """An inbound channel_origin is event data; the trigger decides whose credentials reply."""

    @pytest.fixture
    def trigger(self):
        return WebhookTrigger(
            id=uuid4(),
            name="TG Bot",
            agent_id=uuid4(),
            created_by="user1",
            webhook_id="wh_tg_own",
            webhook_type=WebhookType.TELEGRAM,
            task_parameters={"text": "Answer the user"},
        )

    @pytest.fixture
    def service(self, trigger):
        trigger_repo = AsyncMock()
        trigger_repo.get_trigger.return_value = trigger
        execution_repo = AsyncMock()
        execution_repo.create.return_value = MagicMock(id=uuid4(), trigger_id=trigger.id)
        task_service = AsyncMock()
        task_service.route_or_submit_task.return_value = MagicMock(id=uuid4(), status="submitted")
        return TriggerService(
            repository_factory=make_trigger_repository_factory(
                trigger_repo=trigger_repo, execution_repo=execution_repo
            ),
            event_broker=AsyncMock(),
            task_service=task_service,
        )

    @pytest.mark.asyncio
    async def test_a_foreign_trigger_id_still_replies_with_the_receiving_triggers_token(
        self, service, trigger
    ):
        foreign_trigger_id = str(uuid4())
        await service.execute_trigger(
            trigger.id,
            {
                "events": [{"text": "hi"}],
                "channel_origin": {
                    "type": "a2a_webhook",
                    "trigger_id": foreign_trigger_id,
                    "credential_type": "slack",
                    "url": "http://169.254.169.254/latest",
                    "config_id": "cfg",
                    "task_id": str(uuid4()),
                    "chat_id": "4242",
                    "message_id": 7,
                },
            },
        )

        task = service.task_service.route_or_submit_task.call_args.args[0]
        origin = task.task_parameters["channel_origin"]
        assert origin["trigger_id"] == str(trigger.id)
        assert origin["type"] == "telegram"
        assert origin["credential_type"] == "telegram"
        assert origin["chat_id"] == "4242"
        assert origin["message_id"] == 7
        for smuggled in ("url", "config_id", "task_id"):
            assert smuggled not in origin

        secrets = {
            f"channel_cred:telegram:{trigger.id}": json.dumps({"bot_token": "own-token"}),
            f"channel_cred:telegram:{foreign_trigger_id}": json.dumps(
                {"bot_token": "foreign-token"}
            ),
        }

        class _Reader:
            async def get_secret(self, name: str) -> str | None:
                return secrets.get(name)

        assert await _resolve_token(_Reader(), origin) == "own-token"

    def test_a_polled_mailbox_replies_with_its_own_mailbox_credential(self, service):
        mailbox = CronTrigger(
            id=uuid4(),
            name="Inbox",
            agent_id=uuid4(),
            created_by="user1",
            cron_expression="*/5 * * * *",
            data_extractor="imap",
        )

        origin = service._build_channel_origin(
            mailbox,
            {
                "channel_origin": {
                    "type": "telegram",
                    "credential_type": "smtp_of_someone_else",
                    "trigger_id": str(uuid4()),
                    "chat_id": "<m1@x>",
                    "reply_to": "a@example.com",
                }
            },
        )

        assert origin is not None
        assert origin["type"] == "email"
        assert origin["credential_type"] == "imap"
        assert origin["trigger_id"] == str(mailbox.id)
        assert origin["reply_to"] == "a@example.com"

    def test_a_trigger_with_no_reply_channel_takes_no_supplied_origin(self, service):
        generic = WebhookTrigger(
            id=uuid4(),
            name="Hook",
            agent_id=uuid4(),
            created_by="user1",
            webhook_id="wh_generic",
            webhook_type=WebhookType.GENERIC,
        )

        origin = service._build_channel_origin(
            generic, {"channel_origin": {"type": "web", "trigger_id": str(uuid4())}}
        )

        assert origin is None
