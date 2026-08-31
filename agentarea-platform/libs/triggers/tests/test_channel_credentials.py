"""Tests for channel adapter secret store integration."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.channels.email import EmailAdapter
from agentarea_triggers.channels.exceptions import FatalError
from agentarea_triggers.channels.telegram import TelegramAdapter


class TestTelegramAdapterSecretStore:
    """Test TelegramAdapter credential resolution from secret store."""

    @pytest.fixture
    def secret_manager(self):
        sm = AsyncMock()
        sm.get_secret = AsyncMock(
            return_value=json.dumps({"bot_token": "secret_bot_token"})
        )
        return sm

    @pytest.fixture
    def adapter(self, secret_manager):
        return TelegramAdapter(secret_manager=secret_manager)

    @pytest.mark.asyncio
    async def test_resolves_token_from_secret_store(self, adapter, secret_manager):
        """Derives secret name from type + trigger_id and loads credentials."""
        trigger_id = str(uuid4())
        channel_config = {
            "type": "telegram",
            "trigger_id": trigger_id,
            "chat_id": "12345",
        }

        token = await adapter._resolve_bot_token(channel_config)

        assert token == "secret_bot_token"  # noqa: S105
        secret_manager.get_secret.assert_called_once_with(
            f"channel_cred:telegram:{trigger_id}"
        )

    @pytest.mark.asyncio
    async def test_no_trigger_id_returns_none(self, adapter):
        """Without trigger_id, returns None."""
        channel_config = {"type": "telegram", "chat_id": "12345"}

        token = await adapter._resolve_bot_token(channel_config)

        assert token is None

    @pytest.mark.asyncio
    async def test_no_secret_manager_returns_none(self):
        """Without secret_manager, returns None."""
        adapter = TelegramAdapter()
        channel_config = {
            "type": "telegram",
            "trigger_id": str(uuid4()),
            "chat_id": "12345",
        }

        token = await adapter._resolve_bot_token(channel_config)

        assert token is None

    @pytest.mark.asyncio
    async def test_missing_secret_returns_none(self, secret_manager):
        """If secret store has no entry, returns None."""
        secret_manager.get_secret.return_value = None
        adapter = TelegramAdapter(secret_manager=secret_manager)
        channel_config = {
            "type": "telegram",
            "trigger_id": str(uuid4()),
            "chat_id": "12345",
        }

        token = await adapter._resolve_bot_token(channel_config)

        assert token is None

    @pytest.mark.asyncio
    async def test_secret_without_bot_token_field_returns_none(self, secret_manager):
        """If secret JSON doesn't contain bot_token, returns None."""
        secret_manager.get_secret.return_value = json.dumps({"other_field": "value"})
        adapter = TelegramAdapter(secret_manager=secret_manager)
        channel_config = {
            "type": "telegram",
            "trigger_id": str(uuid4()),
            "chat_id": "12345",
        }

        token = await adapter._resolve_bot_token(channel_config)

        assert token is None


class TestEmailAdapterSecretStore:
    """Test EmailAdapter credential resolution from secret store."""

    @pytest.fixture
    def secret_manager(self):
        sm = AsyncMock()
        sm.get_secret = AsyncMock(
            return_value=json.dumps({
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "username": "user",
                "password": "pass",
                "from_address": "bot@example.com",
                "use_tls": True,
            })
        )
        return sm

    @pytest.fixture
    def adapter(self, secret_manager):
        return EmailAdapter(secret_manager=secret_manager)

    @pytest.mark.asyncio
    async def test_resolves_smtp_creds_from_secret_store(self, adapter, secret_manager):
        """Derives secret name from type + trigger_id and loads SMTP creds."""
        trigger_id = str(uuid4())
        channel_config = {
            "type": "email",
            "trigger_id": trigger_id,
            "reply_to": "user@test.com",
        }

        creds = await adapter._resolve_smtp_credentials(channel_config)

        assert creds is not None
        assert creds["smtp_host"] == "smtp.example.com"
        assert creds["smtp_port"] == 587
        assert creds["use_tls"] is True
        secret_manager.get_secret.assert_called_once_with(
            f"channel_cred:email:{trigger_id}"
        )

    @pytest.mark.asyncio
    async def test_no_trigger_id_raises(self, adapter):
        """Without trigger_id the adapter fails loudly rather than returning None.

        _resolve_smtp_credentials used to return None here, which sent the channel
        on unauthenticated instead of saying it was misconfigured. It now raises
        FatalError — fatal because redelivery cannot fix a missing trigger_id.
        """
        channel_config = {"type": "email", "reply_to": "user@test.com"}

        with pytest.raises(FatalError, match="trigger_id"):
            await adapter._resolve_smtp_credentials(channel_config)

    @pytest.mark.asyncio
    async def test_no_secret_manager_raises(self):
        """Without a secret_manager the adapter fails loudly rather than returning None."""
        adapter = EmailAdapter()
        channel_config = {
            "type": "email",
            "trigger_id": str(uuid4()),
            "reply_to": "user@test.com",
        }

        with pytest.raises(FatalError, match="secret_manager"):
            await adapter._resolve_smtp_credentials(channel_config)


class TestChannelOriginTriggerID:
    """Test that _build_channel_origin includes trigger_id."""

    @pytest.fixture
    def trigger_service(self):
        mock_factory = AsyncMock()
        mock_factory.create_repository.return_value = AsyncMock()
        from agentarea_triggers.trigger_service import TriggerService

        return TriggerService(
            repository_factory=mock_factory,
            event_broker=AsyncMock(),
        )

    def test_telegram_origin_includes_trigger_id(self, trigger_service):
        """Telegram channel_origin should carry trigger_id for credential lookup."""
        from agentarea_triggers.domain.enums import WebhookType
        from agentarea_triggers.domain.models import WebhookTrigger

        trigger = WebhookTrigger(
            name="TG Bot",
            agent_id=uuid4(),
            created_by="user1",
            webhook_id="wh_tg_123",
            webhook_type=WebhookType.TELEGRAM,
        )
        trigger_data = {"chat_id": 12345, "text": "Hello"}

        origin = trigger_service._build_channel_origin(trigger, trigger_data)

        assert origin is not None
        assert origin["trigger_id"] == str(trigger.id)
        assert origin["type"] == "telegram"

    def test_extractor_origin_gets_trigger_id(self, trigger_service):
        """Extractor-provided channel_origin gets trigger_id injected."""
        from agentarea_triggers.domain.models import CronTrigger

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
                "presentation": "summary",
            },
        }

        origin = trigger_service._build_channel_origin(trigger, trigger_data)

        assert origin is not None
        assert origin["trigger_id"] == str(trigger.id)
        assert origin["type"] == "email"
