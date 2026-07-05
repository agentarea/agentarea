"""Tests for channel adapters."""

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

    def test_command_received_seeds_working_frame_in_concise(self):
        """Per-turn WorkflowCommandReceived renders the same '⏳ Working on it...'
        frame as WorkflowStarted. On persistent conversational channels the
        workflow lives across turns (WorkflowStarted fires once ever), so this
        is what seeds the live message before the result edits it in place.
        """
        formatter = make_formatter(TELEGRAM_MD)

        msg = formatter({"event_type": "WorkflowCommandReceived", "data": {}}, "concise")

        assert "Working on it\\.\\.\\." in msg

    def test_command_received_visible_in_concise(self):
        from agentarea_execution.workflows.visibility import PresentationMode, is_visible

        assert is_visible("WorkflowCommandReceived", PresentationMode.CONCISE)

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

    # --- send(): failures must be raised (loud), never swallowed ---------------
    # The delivery consumer classifies on these types: FatalError -> DLQ,
    # RetryableError -> redeliver. Silently returning would make a dead channel
    # look like a successful delivery.

    @pytest.fixture
    def creds(self):
        return json.dumps(
            {
                "smtp_host": "mailpit",
                "smtp_port": 1025,
                "from_address": "agent@agentarea.local",
            }
        )

    @pytest.mark.asyncio
    async def test_send_no_reply_to_raises_fatal(self):
        from agentarea_triggers.channels.exceptions import FatalError

        adapter = EmailAdapter(secret_manager=AsyncMock())
        with pytest.raises(FatalError, match="reply_to"):
            await adapter.send({"trigger_id": "t1"}, "<p>hi</p>")

    @pytest.mark.asyncio
    async def test_send_unresolvable_credentials_raises_fatal(self):
        from agentarea_triggers.channels.exceptions import FatalError

        sm = AsyncMock()
        sm.get_secret = AsyncMock(return_value=None)
        adapter = EmailAdapter(secret_manager=sm)
        with pytest.raises(FatalError, match="credentials not found"):
            await adapter.send({"trigger_id": "t1", "reply_to": "u@x.io"}, "<p>hi</p>")

    @pytest.mark.asyncio
    async def test_send_success_invokes_smtp(self, creds):
        sm = AsyncMock()
        sm.get_secret = AsyncMock(return_value=creds)
        adapter = EmailAdapter(secret_manager=sm)
        with patch(
            "agentarea_triggers.channels.email.aiosmtplib.send", new=AsyncMock()
        ) as send:
            await adapter.send(
                {"trigger_id": "t1", "reply_to": "u@x.io", "subject": "Hi"},
                "<p>hi</p>",
            )
        send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_transient_smtp_error_raises_retryable(self, creds):
        import aiosmtplib
        from agentarea_triggers.channels.exceptions import RetryableError

        sm = AsyncMock()
        sm.get_secret = AsyncMock(return_value=creds)
        adapter = EmailAdapter(secret_manager=sm)
        with patch(
            "agentarea_triggers.channels.email.aiosmtplib.send",
            new=AsyncMock(side_effect=aiosmtplib.SMTPConnectError("refused")),
        ):
            with pytest.raises(RetryableError):
                await adapter.send({"trigger_id": "t1", "reply_to": "u@x.io"}, "<p>hi</p>")

    @pytest.mark.asyncio
    async def test_send_auth_error_raises_fatal(self, creds):
        import aiosmtplib
        from agentarea_triggers.channels.exceptions import FatalError

        sm = AsyncMock()
        sm.get_secret = AsyncMock(return_value=creds)
        adapter = EmailAdapter(secret_manager=sm)
        with patch(
            "agentarea_triggers.channels.email.aiosmtplib.send",
            new=AsyncMock(side_effect=aiosmtplib.SMTPAuthenticationError(535, "bad creds")),
        ):
            with pytest.raises(FatalError, match="authentication"):
                await adapter.send({"trigger_id": "t1", "reply_to": "u@x.io"}, "<p>hi</p>")


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
