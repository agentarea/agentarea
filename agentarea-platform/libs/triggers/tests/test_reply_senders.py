"""The reply senders: the generic HTTP one a catalog reply block describes, the live
Telegram message, SMTP, and the markup flavours they format in (ADR-0040 section 5)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from agentarea_streams.domain.source_types import Reply
from agentarea_triggers.channels import get_adapter
from agentarea_triggers.channels.adapters import make_telegram_live_sender, register_all_adapters
from agentarea_triggers.channels.email import EmailAdapter
from agentarea_triggers.channels.exceptions import FatalError, RetryableError
from agentarea_triggers.channels.http_reply import HttpReplyAdapter
from agentarea_triggers.channels.markup import MARKUPS, format_event, limited, strip_markup

CHAT_REPLY = Reply(
    sender="http",
    target={"channel": "{body:event.channel}", "thread": "{body:event.ts}"},
    request={
        "method": "POST",
        "url": "https://chat.example/api/post",
        "headers": {"Authorization": "Bearer {credentials.bot_token}"},
        "json": {"channel": "{target:channel}", "thread": "{target:thread}", "text": "{message}"},
    },
    markup="slack",
    limit=40,
    permanent_errors=["channel_not_found"],
)


def _config(reply=CHAT_REPLY, target=None, **extra):
    return {
        "type": "chat",
        "sender": reply.sender,
        "credential_type": "chat",
        "credential_key": "key-1",
        "target": {"channel": "C1"} if target is None else target,
        "task_id": "task-1",
        "event_type": "task.completed",
        "workspace_id": "ws-1",
        "owner": "u-1",
        "reply": reply,
        **extra,
    }


class _Credentials:
    def __init__(self, values=None):
        self.values = {"bot_token": "xoxb-1"} if values is None else values
        self.reads: list[dict] = []

    async def __call__(self, **kwargs):
        self.reads.append(kwargs)
        return self.values


def _client(*responses):
    client = AsyncMock()
    client.request = AsyncMock(side_effect=list(responses))
    client.post = AsyncMock(side_effect=list(responses))
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=client)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, client


def _response(status=200, **kwargs):
    return httpx.Response(status, request=httpx.Request("POST", "https://x"), **kwargs)


class TestHttpReply:
    async def test_the_request_is_filled_from_credentials_target_and_message(self):
        credentials = _Credentials()
        factory, client = _client(_response(json={"ok": True}))
        with patch("agentarea_triggers.channels.http_reply.outbound_client", factory):
            await HttpReplyAdapter(credentials).send(_config(), "Report ready")

        method, url = client.request.await_args.args
        kwargs = client.request.await_args.kwargs
        assert (method, url) == ("POST", "https://chat.example/api/post")
        assert kwargs["headers"] == {"Authorization": "Bearer xoxb-1"}
        # A target field the event did not have is left out, not sent empty.
        assert kwargs["json"] == {"channel": "C1", "text": "Report ready"}
        assert credentials.reads == [
            {
                "workspace_id": "ws-1",
                "owner": "u-1",
                "credential_type": "chat",
                "credential_key": "key-1",
            }
        ]

    async def test_a_long_message_is_cut_to_the_entry_limit(self):
        factory, client = _client(_response(json={"ok": True}))
        with patch("agentarea_triggers.channels.http_reply.outbound_client", factory):
            await HttpReplyAdapter(_Credentials()).send(_config(), "x" * 100)
        text = client.request.await_args.kwargs["json"]["text"]
        assert len(text) == 40
        assert text.endswith("_(truncated)_")

    async def test_a_credential_the_request_needs_and_lacks_is_permanent(self):
        factory, client = _client()
        with patch("agentarea_triggers.channels.http_reply.outbound_client", factory):
            with pytest.raises(FatalError, match="Authorization"):
                await HttpReplyAdapter(_Credentials({})).send(_config(), "hi")
        client.request.assert_not_awaited()

    async def test_an_ok_false_answer_naming_a_permanent_error_is_permanent(self):
        factory, _ = _client(_response(json={"ok": False, "error": "channel_not_found"}))
        with patch("agentarea_triggers.channels.http_reply.outbound_client", factory):
            with pytest.raises(FatalError, match="channel_not_found"):
                await HttpReplyAdapter(_Credentials()).send(_config(), "hi")

    async def test_an_ok_false_answer_otherwise_is_retried(self):
        factory, _ = _client(_response(json={"ok": False, "error": "ratelimited"}))
        with patch("agentarea_triggers.channels.http_reply.outbound_client", factory):
            with pytest.raises(RetryableError):
                await HttpReplyAdapter(_Credentials()).send(_config(), "hi")

    @pytest.mark.parametrize(
        ("status", "error"), [(429, RetryableError), (502, RetryableError), (403, FatalError)]
    )
    async def test_http_failures_are_classified(self, status, error):
        factory, _ = _client(_response(status, text="nope"))
        with patch("agentarea_triggers.channels.http_reply.outbound_client", factory):
            with pytest.raises(error):
                await HttpReplyAdapter(_Credentials()).send(_config(), "hi")

    async def test_a_network_failure_is_retried(self):
        factory, client = _client()
        client.request = AsyncMock(side_effect=httpx.ConnectTimeout("down"))
        with patch("agentarea_triggers.channels.http_reply.outbound_client", factory):
            with pytest.raises(RetryableError):
                await HttpReplyAdapter(_Credentials()).send(_config(), "hi")

    def test_it_formats_in_the_entry_markup(self):
        event = {"event_type": "task.failed", "data": {"error": "boom"}}
        assert HttpReplyAdapter(_Credentials()).format(event, "concise", _config()) == (
            ":x: *Failed* — boom"
        )


class TestMarkup:
    def test_a_completed_task_sends_its_final_answer(self):
        event = {"event_type": "task.completed", "data": {"final_response": "Done.", "result": {}}}
        assert format_event(MARKUPS["telegram"], event, "concise") == "Done\\."

    @pytest.mark.parametrize("name", sorted(MARKUPS))
    def test_a_denial_says_the_call_was_denied(self, name):
        event = {"event_type": "approval.decided", "data": {"approved": False, "comment": "no"}}
        message = format_event(MARKUPS[name], event, "concise")
        assert "denied" in message.lower()
        assert "continuing" not in message.lower()

    @pytest.mark.parametrize("name", sorted(MARKUPS))
    def test_a_response_without_a_decision_claims_neither(self, name):
        event = {"event_type": "approval.decided", "data": {}}
        message = format_event(MARKUPS[name], event, "concise").lower()
        assert "denied" not in message
        assert "approved" not in message
        assert "resolved" in message

    def test_limited_keeps_short_messages(self):
        assert limited(MARKUPS["plain"], "hi", 10) == "hi"
        assert limited(MARKUPS["plain"], "hi", None) == "hi"

    def test_strip_markup_for_a_plain_resend(self):
        assert strip_markup(r"\*Done\* with value\_1") == "Done with value1"


class TestTelegramLive:
    @pytest.fixture
    def store(self):
        return {}

    @pytest.fixture
    def sender(self, store):
        fake_redis = AsyncMock()
        fake_redis.hgetall = AsyncMock(side_effect=lambda k: dict(store.get(k, {})))
        fake_redis.hset = AsyncMock(
            side_effect=lambda k, mapping: store.setdefault(k, {}).update(mapping)
        )
        fake_redis.expire = AsyncMock(return_value=True)
        fake_redis.delete = AsyncMock(side_effect=lambda k: store.pop(k, None))
        with patch("redis.asyncio.from_url", return_value=fake_redis):
            return make_telegram_live_sender(_Credentials({"bot_token": "123:ABC"}), "redis://x")

    async def test_the_feed_collapses_to_the_answer_on_the_terminal_event(self, sender, store):
        posts: list = []

        async def _post(url, **kw):
            posts.append((url, kw.get("json")))
            return _response(json={"ok": True, "result": {"message_id": 555}})

        factory, client = _client()
        client.post = AsyncMock(side_effect=_post)
        reply = Reply(sender="telegram_live", markup="telegram")
        base = _config(reply=reply, target={"chat_id": 42, "message_id": 7})
        with patch("agentarea_triggers.channels.adapters.outbound_client", factory):
            await sender({**base, "event_type": "task.started"}, r"Working on it\.\.\.")
            await sender({**base, "event_type": "task.completed"}, "Report ready")

        url, first = posts[0]
        assert url == "https://api.telegram.org/bot123:ABC/sendMessage"
        assert (first["chat_id"], first["reply_to_message_id"]) == (42, 7)
        edit_url, edit = posts[-1]
        assert edit_url.endswith("/editMessageText")
        assert edit["text"] == "Report ready"
        assert store == {}

    async def test_a_parse_error_is_resent_without_markup(self, sender):
        factory, client = _client(
            _response(400, text="Bad Request: can't parse entities"),
            _response(json={"ok": True, "result": {"message_id": 1}}),
        )
        reply = Reply(sender="telegram_live", markup="telegram")
        with patch("agentarea_triggers.channels.adapters.outbound_client", factory):
            await sender(_config(reply=reply, target={"chat_id": 42}), r"\*Done\*")
        retry = client.post.await_args_list[1].kwargs["json"]
        assert "parse_mode" not in retry
        assert retry["text"] == "Done"

    async def test_an_address_without_a_chat_is_permanent(self, sender):
        reply = Reply(sender="telegram_live", markup="telegram")
        with pytest.raises(FatalError, match="chat_id"):
            await sender(_config(reply=reply, target={"message_id": 7}), "hi")


async def _no_network(host, port):
    return MagicMock()


SMTP = {"smtp_host": "mailpit", "smtp_port": 1025, "from_address": "agent@agentarea.local"}


class TestSmtp:
    def _config(self, **target):
        return _config(
            reply=Reply(sender="smtp", presentation="summary"),
            target={"to": "u@x.io", **target},
        )

    async def test_it_connects_to_the_vetted_address_and_keeps_the_name_for_tls(self):
        connected: list = []
        sock = MagicMock()

        async def connect(host, port):
            connected.append((host, port))
            return sock

        adapter = EmailAdapter(_Credentials(SMTP), connect=connect)
        with patch("agentarea_triggers.channels.email.aiosmtplib.send", new=AsyncMock()) as send:
            await adapter.send(self._config(), "<p>hi</p>")
        assert connected == [("mailpit", 1025)]
        assert send.await_args.kwargs["sock"] is sock

    async def test_a_refused_host_is_permanent(self):
        from agentarea_common.utils.url_safety import UnsafeUrlError

        async def refuse(host, port):
            raise UnsafeUrlError("private address")

        adapter = EmailAdapter(_Credentials(SMTP), connect=refuse)
        with pytest.raises(FatalError, match="refused"):
            await adapter.send(self._config(), "<p>hi</p>")

    async def test_no_smtp_host_is_permanent(self):
        adapter = EmailAdapter(_Credentials({"from_address": "a@b.io"}), connect=_no_network)
        with pytest.raises(FatalError, match="smtp_host"):
            await adapter.send(self._config(), "<p>hi</p>")

    async def test_a_target_with_no_sender_address_is_permanent(self):
        adapter = EmailAdapter(_Credentials(SMTP), connect=_no_network)
        config = _config(reply=Reply(sender="smtp"), target={"subject": "x"})
        with pytest.raises(FatalError, match="no address"):
            await adapter.send(config, "<p>hi</p>")

    async def test_a_transient_smtp_error_is_retried(self):
        import aiosmtplib

        adapter = EmailAdapter(_Credentials(SMTP), connect=_no_network)
        with patch(
            "agentarea_triggers.channels.email.aiosmtplib.send",
            new=AsyncMock(side_effect=aiosmtplib.SMTPConnectError("refused")),
        ):
            with pytest.raises(RetryableError):
                await adapter.send(self._config(), "<p>hi</p>")

    async def test_the_reply_threads_under_the_whole_chain(self):
        adapter = EmailAdapter(_Credentials(SMTP), connect=_no_network)
        with patch("agentarea_triggers.channels.email.aiosmtplib.send", new=AsyncMock()) as send:
            await adapter.send(
                self._config(message_id="<second@x>", references="<root@x>", subject="Re: hi"),
                "<p>hi</p>",
            )
        message = send.await_args.args[0]
        assert message["In-Reply-To"] == "<second@x>"
        assert message["References"] == "<root@x> <second@x>"
        assert message["Subject"] == "Re: hi"

    def test_a_completed_task_mails_its_final_answer(self):
        html = EmailAdapter(_Credentials(SMTP)).format(
            {"event_type": "task.completed", "data": {"final_response": "PONG"}}, "summary", {}
        )
        assert "PONG" in html


def test_senders_register_under_their_reply_sender_names():
    with patch("redis.asyncio.from_url", return_value=AsyncMock()):
        register_all_adapters(AsyncMock(), _Credentials(), "redis://x")
    for name in ("http", "telegram_live", "smtp", "a2a_webhook", "task_webhook"):
        assert get_adapter(name) is not None
