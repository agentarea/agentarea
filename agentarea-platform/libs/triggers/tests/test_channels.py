"""Tests for channel adapters and router."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agentarea_triggers.channels import get_adapter, list_adapters, register_adapter
from agentarea_triggers.channels.adapters import (
    TELEGRAM_MD,
    TELEGRAM_SENDER,
    _strip_markdown,
    make_formatter,
    make_http_sender,
)
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
    def secret_manager(self):
        sm = AsyncMock()
        sm.get_secret = AsyncMock(
            return_value=json.dumps({"bot_token": "test-token"})
        )
        return sm

    @pytest.fixture
    def adapter(self, secret_manager):
        return TelegramAdapter(secret_manager=secret_manager)

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
        channel_config = {"type": "telegram", "trigger_id": "test-trigger", "chat_id": "12345"}
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
    async def test_send_no_secret_key_logs_error(self):
        """Without secret_key, send logs error and returns."""
        adapter = TelegramAdapter()
        channel_config = {"chat_id": "12345"}
        # Should not raise, just log
        await adapter.send(channel_config, "Hello")

    @pytest.mark.asyncio
    async def test_send_no_chat_id_logs_error(self, adapter):
        channel_config = {"type": "telegram", "trigger_id": "test-trigger"}
        await adapter.send(channel_config, "Hello")

    def test_escape_md(self):
        assert _escape_md("hello_world") == "hello\\_world"
        assert _escape_md("*bold*") == "\\*bold\\*"
        assert _escape_md("normal") == "normal"


class TestComposedTelegramAdapter:
    """Test the composed Telegram adapter used by the worker."""

    @pytest.fixture
    def secret_manager(self):
        sm = AsyncMock()
        sm.get_secret = AsyncMock(
            return_value=json.dumps({"bot_token": "test-token"})
        )
        return sm

    def test_formatter_escapes_status_punctuation_for_markdown_v2(self):
        formatter = make_formatter(TELEGRAM_MD)

        msg = formatter({"event_type": "WorkflowStarted", "data": {}}, "concise")

        assert "Working on it\\.\\.\\." in msg

    def test_strip_markdown_for_plain_text_fallback(self):
        assert _strip_markdown(r"\*Done\* with value\_1") == "Done with value1"

    @pytest.mark.asyncio
    async def test_sender_retries_without_markdown_on_telegram_parse_error(self, secret_manager):
        sender = make_http_sender(TELEGRAM_SENDER, secret_manager)
        channel_config = {
            "type": "telegram",
            "trigger_id": "test-trigger",
            "chat_id": "12345",
            "message_id": 99,
        }
        bad_resp = httpx.Response(
            400,
            text="Bad Request: can't parse entities",
            request=httpx.Request("POST", "https://telegram.test/sendMessage"),
        )
        ok_resp = httpx.Response(
            200,
            json={"ok": True},
            request=httpx.Request("POST", "https://telegram.test/sendMessage"),
        )

        with patch("agentarea_triggers.channels.adapters.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [bad_resp, ok_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await sender(channel_config, r"⏳ Working on it\.\.\.")

            assert mock_client.post.call_count == 2
            first_payload = mock_client.post.call_args_list[0].kwargs["json"]
            retry_payload = mock_client.post.call_args_list[1].kwargs["json"]
            assert first_payload["parse_mode"] == "MarkdownV2"
            assert "parse_mode" not in retry_payload
            assert retry_payload["text"] == "⏳ Working on it..."
            assert retry_payload["reply_to_message_id"] == 99


class TestEmailAdapter:
    """Test Email outbound adapter."""

    @pytest.fixture
    def adapter(self):
        return EmailAdapter()

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
    def emitter(self):
        # Router now submits to a stream emitter instead of calling adapter.send
        # directly — the consumer drives delivery in a separate loop.
        e = AsyncMock()
        e.submit = AsyncMock(return_value="msg-id-1")
        return e

    @pytest.fixture
    def router(self, emitter):
        return ChannelRouter(emitter=emitter)

    @pytest.mark.asyncio
    async def test_no_channel_origin_skips(self, router, emitter):
        """Events without channel_origin are ignored (webUI handles them)."""
        event = {"event_type": "WorkflowCompleted", "data": {}}
        await router.on_task_event(event)
        emitter.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_invisible_event_skipped(self, router, emitter):
        """Events not visible in the presentation mode are skipped."""
        event = {
            "event_type": "LLMCallChunk",  # Internal — not visible in concise
            "data": {},
            "channel_origin": {"type": "telegram", "chat_id": "123", "presentation": "concise"},
        }
        await router.on_task_event(event)
        emitter.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatches_to_registered_adapter(self, router, emitter):
        """Events are formatted by the adapter and submitted to the emitter."""
        from unittest.mock import MagicMock
        mock_adapter = MagicMock()
        # format is sync, returns the message string
        mock_adapter.format = MagicMock(return_value="formatted message")
        # send is async — would be called by the consumer, not by the router
        mock_adapter.send = AsyncMock()
        register_adapter("test_channel", mock_adapter)

        event = {
            "event_type": "WorkflowCompleted",
            "data": {"result": "done"},
            "channel_origin": {"type": "test_channel", "chat_id": "123", "presentation": "concise"},
        }

        await router.on_task_event(event)

        mock_adapter.format.assert_called_once()
        # send is NOT called by the router anymore — the consumer does that.
        mock_adapter.send.assert_not_called()
        emitter.submit.assert_called_once()
        kwargs = emitter.submit.await_args.kwargs
        assert kwargs["channel_type"] == "test_channel"
        assert kwargs["message"] == "formatted message"

    @pytest.mark.asyncio
    async def test_missing_adapter_logs_warning(self, router, emitter):
        """Missing adapter logs a warning but doesn't raise or submit."""
        event = {
            "event_type": "WorkflowCompleted",
            "data": {},
            "channel_origin": {"type": "nonexistent_channel", "chat_id": "123"},
        }
        await router.on_task_event(event)
        emitter.submit.assert_not_called()


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
        adapter = create_telegram_adapter()
        assert isinstance(adapter, TelegramAdapter)
        assert get_adapter("telegram") is adapter

    def test_create_email_adapter_registers(self):
        adapter = create_email_adapter()
        assert isinstance(adapter, EmailAdapter)
        assert get_adapter("email") is adapter
