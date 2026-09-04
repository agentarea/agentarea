"""Unit tests for the extensible inbound-webhook registration layer.

Mirrors the outbound ChannelAdapter registry: a per-channel WebhookRegistrar
capability + a registry + a thin application service. Adding a channel must not
touch the service or the controller.
"""

from unittest.mock import AsyncMock, patch

import pytest
from agentarea_triggers.channels import (
    get_webhook_registrar,
    register_webhook_registrar,
)
from agentarea_triggers.channels.webhook_service import ChannelWebhookService


class _FakeRegistrar:
    def __init__(self):
        self.registered = None
        self.deregistered = None

    async def register(self, *, webhook_url, credentials, secret_token=None):
        self.registered = (webhook_url, credentials, secret_token)
        return True

    async def deregister(self, *, credentials):
        self.deregistered = credentials


@pytest.mark.asyncio
async def test_service_builds_url_and_delegates_to_registrar():
    fake = _FakeRegistrar()
    register_webhook_registrar("faketg", fake)
    svc = ChannelWebhookService(base_url="https://gw.example/")

    ok = await svc.register(channel_type="faketg", webhook_id="wh1", credentials={"bot_token": "t"})

    assert ok is True
    assert fake.registered[0] == "https://gw.example/webhooks/wh1"
    assert fake.registered[1] == {"bot_token": "t"}


@pytest.mark.asyncio
async def test_service_is_noop_for_unregistered_channel():
    svc = ChannelWebhookService(base_url="https://gw.example")
    ok = await svc.register(channel_type="nope", webhook_id="wh1", credentials={})
    assert ok is False


@pytest.mark.asyncio
async def test_service_is_noop_without_base_url():
    fake = _FakeRegistrar()
    register_webhook_registrar("faketg2", fake)
    svc = ChannelWebhookService(base_url="")
    ok = await svc.register(channel_type="faketg2", webhook_id="wh1", credentials={})
    assert ok is False
    assert fake.registered is None


@pytest.mark.asyncio
async def test_service_deregister_delegates_to_registrar():
    fake = _FakeRegistrar()
    register_webhook_registrar("faketg3", fake)
    svc = ChannelWebhookService(base_url="https://x")
    await svc.deregister(channel_type="faketg3", credentials={"bot_token": "t"})
    assert fake.deregistered == {"bot_token": "t"}


@pytest.mark.asyncio
async def test_telegram_registrar_is_registered_and_calls_set_webhook():
    from agentarea_triggers.channels.telegram import TelegramWebhookRegistrar

    reg = get_webhook_registrar("telegram")
    assert isinstance(reg, TelegramWebhookRegistrar)

    with patch(
        "agentarea_triggers.channels.telegram.set_webhook",
        new=AsyncMock(return_value=True),
    ) as sw:
        ok = await reg.register(
            webhook_url="https://x/webhooks/wh1",
            credentials={"bot_token": "123:ABC"},
            secret_token="s",  # noqa: S106
        )
        assert ok is True
        sw.assert_awaited_once_with("123:ABC", "https://x/webhooks/wh1", "s")


@pytest.mark.asyncio
async def test_telegram_registrar_deregister_calls_delete_webhook():
    reg = get_webhook_registrar("telegram")
    with patch(
        "agentarea_triggers.channels.telegram.delete_webhook",
        new=AsyncMock(return_value=True),
    ) as dw:
        await reg.deregister(credentials={"bot_token": "123:ABC"})
        dw.assert_awaited_once_with("123:ABC")
