"""Tests for channel adapters and router."""

from unittest.mock import AsyncMock, patch

import pytest
from agentarea_triggers.channels import get_adapter, list_adapters, register_adapter
from agentarea_triggers.channels.email import (
    EmailAdapter,
    _escape_html,
    _html_to_plain,
    create_email_adapter,
)
from agentarea_triggers.channels.router import ChannelRouter
from agentarea_triggers.channels.telegram import (
    TelegramAdapter,
    _escape_md,
    create_telegram_adapter,
)


class TestTelegramAdapter:
    """Test Telegram outbound adapter."""

    @pytest.fixture
    def adapter(self):
        return TelegramAdapter(bot_token="test-token")

    def test_format_workflow_completed(self, adapter):
        event = {"event_type": "WorkflowCompleted", "data": {"result": "Done!"}}
        msg = adapter.format(event, "concise")
        assert "Done" in msg
        assert "Done" in msg or "\\!" in msg

    def test_format_workflow_failed(self, adapter):
        event = {"event_type": "WorkflowFailed", "data": {"error": "Timeout"}}
        msg = adapter.format(event, "concise")
        assert "Failed" in msg

    def test_format_human_approval(self, adapter):
        event = {"event_type": "HumanApprovalRequested", "data": {"question": "Proceed?"}}
        msg = adapter.format(event, "concise")
        assert "input" in msg.lower() or "Proceed" in msg

    def test_format_status_in_concise(self, adapter):
        event = {"event_type": "WorkflowStarted", "data": {}}
        msg = adapter.format(event, "concise")
        assert "Working" in msg

    def test_format_tool_call(self, adapter):
        event = {"event_type": "ToolCallStarted", "data": {"tool_name": "web_search"}}
        msg = adapter.format(event, "concise")
        assert "web" in msg.lower() or "search" in msg.lower()

    @pytest.mark.asyncio
    async def test_send_calls_bot_api(self, adapter):
        channel_config = {"chat_id": "12345", "bot_token": "test-token"}
        with patch("agentarea_triggers.channels.telegram.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.is_success = True
            mock_resp.raise_for_status = lambda: None
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await adapter.send(channel_config, "Hello")

            mock_client.post.assert_called_once()
            args, kwargs = mock_client.post.call_args
            assert "sendMessage" in args[0]
            assert kwargs["json"]["chat_id"] == "12345"
            assert kwargs["json"]["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_send_no_token_logs_error(self, adapter):
        adapter.bot_token = None
        channel_config = {"chat_id": "12345"}
        # Should not raise, just log
        await adapter.send(channel_config, "Hello")

    @pytest.mark.asyncio
    async def test_send_no_chat_id_logs_error(self, adapter):
        channel_config = {"bot_token": "test-token"}
        await adapter.send(channel_config, "Hello")

    def test_escape_md(self):
        assert _escape_md("hello_world") == "hello\\_world"
        assert _escape_md("*bold*") == "\\*bold\\*"
        assert _escape_md("normal") == "normal"


class TestEmailAdapter:
    """Test Email outbound adapter."""

    @pytest.fixture
    def adapter(self):
        return EmailAdapter(smtp_host="localhost", smtp_port=25)

    def test_format_workflow_completed(self, adapter):
        event = {"event_type": "WorkflowCompleted", "data": {"result": "Report generated"}}
        html = adapter.format(event, "summary")
        assert "Report generated" in html
        assert "Complete" in html

    def test_format_workflow_failed(self, adapter):
        event = {"event_type": "WorkflowFailed", "data": {"error": "API timeout"}}
        html = adapter.format(event, "summary")
        assert "API timeout" in html
        assert "Failed" in html

    def test_format_human_approval(self, adapter):
        event = {"event_type": "HumanApprovalRequested", "data": {"question": "Approve deploy?"}}
        html = adapter.format(event, "summary")
        assert "Approve deploy?" in html

    def test_escape_html(self):
        assert _escape_html("<script>") == "&lt;script&gt;"
        assert _escape_html("a & b") == "a &amp; b"

    def test_html_to_plain(self):
        html = "<p>Hello <strong>world</strong></p>"
        assert "Hello world" in _html_to_plain(html)


class TestChannelRouter:
    """Test channel router dispatch."""

    @pytest.fixture
    def router(self):
        return ChannelRouter()

    @pytest.mark.asyncio
    async def test_no_channel_origin_skips(self, router):
        """Events without channel_origin are ignored (webUI handles them)."""
        event = {"event_type": "WorkflowCompleted", "data": {}}
        # Should not raise
        await router.on_task_event(event)

    @pytest.mark.asyncio
    async def test_invisible_event_skipped(self, router):
        """Events not visible in the presentation mode are skipped."""
        event = {
            "event_type": "LLMCallChunk",  # Internal — not visible in concise
            "data": {},
            "channel_origin": {"type": "telegram", "chat_id": "123", "presentation": "concise"},
        }
        # Should not raise or attempt to send
        await router.on_task_event(event)

    @pytest.mark.asyncio
    async def test_dispatches_to_registered_adapter(self, router):
        """Events are dispatched to the correct adapter."""
        mock_adapter = AsyncMock()
        mock_adapter.format.return_value = "formatted message"
        register_adapter("test_channel", mock_adapter)

        event = {
            "event_type": "WorkflowCompleted",
            "data": {"result": "done"},
            "channel_origin": {"type": "test_channel", "chat_id": "123", "presentation": "concise"},
        }

        await router.on_task_event(event)

        mock_adapter.format.assert_called_once()
        mock_adapter.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_adapter_logs_warning(self, router):
        """Missing adapter logs a warning but doesn't raise."""
        event = {
            "event_type": "WorkflowCompleted",
            "data": {},
            "channel_origin": {"type": "nonexistent_channel", "chat_id": "123"},
        }
        await router.on_task_event(event)


class TestAdapterRegistry:
    """Test channel adapter registry."""

    def test_register_and_get(self):
        mock = AsyncMock()
        register_adapter("test_reg", mock)
        assert get_adapter("test_reg") is mock

    def test_get_nonexistent(self):
        assert get_adapter("does_not_exist") is None

    def test_list_adapters(self):
        register_adapter("listed_adapter", AsyncMock())
        names = list_adapters()
        assert "listed_adapter" in names

    def test_create_telegram_adapter_registers(self):
        adapter = create_telegram_adapter("token123")
        assert isinstance(adapter, TelegramAdapter)
        assert get_adapter("telegram") is adapter

    def test_create_email_adapter_registers(self):
        adapter = create_email_adapter()
        assert isinstance(adapter, EmailAdapter)
        assert get_adapter("email") is adapter
