"""Tests for channel_origin flow: trigger → task_parameters → router dispatch."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.channels import register_adapter
from agentarea_triggers.channels.router import ChannelRouter
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


class TestRouterWithTaskLookup:
    """Test ChannelRouter with task_lookup for resolving channel_origin.

    The router now hands off to a `ChannelDeliveryEmitter` instead of
    calling `adapter.send` inline — the actual delivery is the consumer's
    job. Tests assert `emitter.submit` was called with the right shape.
    """

    @pytest.fixture
    def emitter(self):
        e = AsyncMock()
        e.submit = AsyncMock(return_value="msg-id-1")
        return e

    @pytest.mark.asyncio
    async def test_router_resolves_origin_from_lookup(self, emitter):
        """Router looks up task params to find channel_origin, then formats
        + submits to the delivery stream."""
        from unittest.mock import MagicMock
        mock_adapter = MagicMock()
        mock_adapter.format = MagicMock(return_value="formatted")
        mock_adapter.send = AsyncMock()
        register_adapter("telegram_lookup_test", mock_adapter)

        async def mock_task_lookup(task_id: str):
            return {
                "channel_origin": {
                    "type": "telegram_lookup_test",
                    "chat_id": "12345",
                    "presentation": "concise",
                }
            }

        router = ChannelRouter(emitter=emitter, task_lookup=mock_task_lookup)

        event = {
            "event_type": "WorkflowCompleted",
            "task_id": str(uuid4()),
            "event_id": str(uuid4()),
            "data": {"result": "Done"},
        }

        await router.on_task_event(event)

        mock_adapter.format.assert_called_once()
        # Router no longer calls send directly — that's the consumer's job.
        mock_adapter.send.assert_not_called()
        emitter.submit.assert_called_once()
        kwargs = emitter.submit.await_args.kwargs
        assert kwargs["channel_type"] == "telegram_lookup_test"
        assert kwargs["message"] == "formatted"

    @pytest.mark.asyncio
    async def test_router_caches_lookup_result(self, emitter):
        """Router caches channel_origin per task to avoid repeated DB lookups
        across non-terminal events. (Terminal events evict the cache, by
        design — covered separately below.)
        """
        from unittest.mock import MagicMock
        call_count = 0

        async def counting_lookup(task_id: str):
            nonlocal call_count
            call_count += 1
            return {"channel_origin": {"type": "telegram_cache_test", "chat_id": "1", "presentation": "concise"}}

        mock_adapter = MagicMock()
        mock_adapter.format = MagicMock(return_value="msg")
        mock_adapter.send = AsyncMock()
        register_adapter("telegram_cache_test", mock_adapter)

        router = ChannelRouter(emitter=emitter, task_lookup=counting_lookup)
        task_id = str(uuid4())

        # Two non-terminal events on the same task → one lookup.
        for event_type in ("WorkflowStarted", "ToolCallStarted"):
            await router.on_task_event({
                "event_type": event_type,
                "task_id": task_id,
                "event_id": str(uuid4()),
                "data": {},
            })

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_router_no_lookup_no_origin_skips(self, emitter):
        """Without task_lookup or channel_origin, event is skipped (no submit)."""
        router = ChannelRouter(emitter=emitter, task_lookup=None)

        event = {"event_type": "WorkflowCompleted", "task_id": str(uuid4()), "data": {}}
        await router.on_task_event(event)
        emitter.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_router_clear_cache(self, emitter):
        """Cache can be cleared per task or entirely."""
        router = ChannelRouter(emitter=emitter)
        router._origin_cache["task1"] = {"type": "telegram"}
        router._origin_cache["task2"] = {"type": "email"}

        router.clear_cache("task1")
        assert "task1" not in router._origin_cache
        assert "task2" in router._origin_cache

        router.clear_cache()
        assert len(router._origin_cache) == 0
