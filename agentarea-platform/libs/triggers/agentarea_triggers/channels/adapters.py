"""The reply senders, keyed by the name a delivery address or target gives (ADR-0040 §5).

``http`` is the generic sender a catalog entry's ``reply`` block describes.
What takes more than one request stays here: the live Telegram message edited in
place (``telegram_live``), SMTP (``smtp``), and our own protocols, A2A push
notifications (``a2a_webhook``) and the task webhook (``task_webhook``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import httpx
from agentarea_common.events.contract import (
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    canonical_type,
)
from agentarea_common.outbound import Destination, outbound_client

from . import register_adapter
from .email import create_email_adapter
from .exceptions import FatalError, RetryableError
from .http_reply import HttpReplyAdapter, raise_for_reply, reply_of
from .markup import format_event, markup, strip_markup
from .source_credentials import CredentialReader, credentials_of

if TYPE_CHECKING:
    from .secret_reader import SecretReader

logger = logging.getLogger(__name__)


class _ComposedAdapter:
    """Wraps a (formatter, sender) pair into the ChannelAdapter protocol."""

    def __init__(
        self,
        formatter: Callable[[dict[str, Any], str, dict[str, Any]], str],
        sender: Callable[[dict[str, Any], str], Awaitable[None]],
    ):
        self._format = formatter
        self._send = sender

    def format(self, event: dict[str, Any], presentation: str, config: dict[str, Any]) -> str:
        return self._format(event, presentation, config)

    async def send(self, channel_config: dict[str, Any], message: str) -> None:
        await self._send(channel_config, message)


# ── A2A push webhook adapter ──────────────────────────────────────


def _a2a_webhook_format(event: dict[str, Any], presentation: str, config: dict[str, Any]) -> str:
    """Format a workflow event as an A2A push-notification body (terminal only)."""
    from agentarea_common.utils.a2a_push import build_push_notification_body

    return build_push_notification_body(event) or ""


def make_a2a_webhook_sender(
    secret_reader: SecretReader,
) -> Callable[[dict[str, Any], str], Awaitable[None]]:
    """Build the sender that POSTs an A2A notification to a client webhook.

    The webhook ``url`` is client-supplied, so it is SSRF-validated before every
    send. The callback ``token`` lives in the secret store (never in task params)
    and is echoed in ``X-A2A-Notification-Token`` so the client can authenticate us.
    """

    async def _send(channel_config: dict[str, Any], message: str) -> None:
        from agentarea_common.utils.a2a_push import push_token_secret_name
        from agentarea_common.utils.url_safety import (
            OutboundPolicy,
            UnsafeUrlError,
            safe_async_client,
        )

        url = channel_config.get("url")
        if not url or not message:
            return

        headers = {"Content-Type": "application/json"}
        task_id = channel_config.get("task_id")
        config_id = channel_config.get("config_id")
        if task_id and config_id:
            token = await secret_reader.get_secret(push_token_secret_name(task_id, config_id))
            if token:
                headers["X-A2A-Notification-Token"] = token

        try:
            # The URL is an A2A client's, not a member's: the deployment's
            # private allowances for member endpoints do not extend to it.
            async with safe_async_client(policy=OutboundPolicy(), timeout=30.0) as client:
                resp = await client.post(url, content=message, headers=headers)
        except UnsafeUrlError as e:
            # Misconfigured/hostile target — do not retry.
            raise FatalError(f"unsafe push webhook url: {e}") from e
        except httpx.HTTPError as e:
            raise RetryableError(f"push webhook network error: {e}") from e

        if resp.status_code >= 500 or resp.status_code == 429:
            raise RetryableError(f"push webhook returned {resp.status_code}")
        if resp.status_code >= 400:
            raise FatalError(f"push webhook returned {resp.status_code}")

    return _send


def make_a2a_webhook_adapter(secret_reader: SecretReader) -> _ComposedAdapter:
    return _ComposedAdapter(
        formatter=_a2a_webhook_format,
        sender=make_a2a_webhook_sender(secret_reader),
    )


# ── Task webhook adapter ──────────────────────────────────────────


def _task_webhook_format(event: dict[str, Any], presentation: str, config: dict[str, Any]) -> str:
    """Format a terminal task event as the task webhook body (terminal only)."""
    from agentarea_common.utils.task_webhook import build_task_webhook_body

    return build_task_webhook_body(event) or ""


def make_task_webhook_sender(
    secret_reader: SecretReader,
) -> Callable[[dict[str, Any], str], Awaitable[None]]:
    """Build the sender that POSTs a task webhook delivery to the API caller.

    The URL is caller-supplied, so it goes through the pinned client on every
    send. A signed webhook whose secret is not readable yet (the API
    stores it right after starting the task) is retried rather than sent unsigned.
    """

    async def _send(channel_config: dict[str, Any], message: str) -> None:
        import time

        from agentarea_common.utils.task_webhook import (
            DELIVERY_HEADER,
            EVENT_HEADER,
            SIGNATURE_HEADER,
            sign,
            webhook_secret_name,
        )
        from agentarea_common.utils.url_safety import (
            OutboundPolicy,
            UnsafeUrlError,
            safe_async_client,
        )

        url = channel_config.get("url")
        if not url or not message:
            return

        body = json.loads(message)
        headers = {
            "Content-Type": "application/json",
            EVENT_HEADER: str(body.get("type") or channel_config.get("event_type") or ""),
            DELIVERY_HEADER: str(body.get("event_id") or ""),
        }
        if channel_config.get("signed"):
            task_id = str(channel_config.get("task_id") or "")
            secret = await secret_reader.get_secret(webhook_secret_name(task_id))
            if not secret:
                raise RetryableError("task webhook secret is not readable yet")
            headers[SIGNATURE_HEADER] = sign(secret, message, int(time.time()))

        try:
            # Set by an API key of the workspace, so the deployment's outbound
            # policy applies, as it does when the task is created.
            async with safe_async_client(policy=OutboundPolicy.from_env(), timeout=30.0) as client:
                resp = await client.post(url, content=message, headers=headers)
        except UnsafeUrlError as e:
            raise FatalError(f"unsafe task webhook url: {e}") from e
        except httpx.HTTPError as e:
            raise RetryableError(f"task webhook network error: {e}") from e

        if resp.status_code >= 500 or resp.status_code == 429:
            raise RetryableError(f"task webhook returned {resp.status_code}")
        if resp.status_code >= 400:
            raise FatalError(f"task webhook returned {resp.status_code}")

    return _send


def make_task_webhook_adapter(secret_reader: SecretReader) -> _ComposedAdapter:
    return _ComposedAdapter(
        formatter=_task_webhook_format,
        sender=make_task_webhook_sender(secret_reader),
    )


# ── Telegram live message ─────────────────────────────────────────


def _telegram_live_format(event: dict[str, Any], presentation: str, config: dict[str, Any]) -> str:
    return format_event(markup(reply_of(config).markup), event, presentation)


def make_telegram_live_sender(
    credentials: CredentialReader,
    redis_url: str,
) -> Callable[[dict[str, Any], str], Awaitable[None]]:
    """Telegram sender that streams progress into ONE live message.

    The first event of a task sends a message and every later one edits it,
    accumulating the activity feed; the terminal event replaces the feed with
    the answer. Per-task state (the message id and the feed) lives in Redis
    keyed by task id, so it survives redeliveries and worker restarts. The chat
    and the message to answer come from the address's target; the bot token
    from the source's credentials.
    """
    import redis.asyncio as aioredis

    # redis-py types async command results as ResponseT (Awaitable[T] | T), so a
    # precise annotation makes pyright reject the awaits; keep the client loose.
    _redis: Any = aioredis.from_url(redis_url, decode_responses=True)
    _terminal = {TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED}

    def _api(token: str, method: str) -> str:
        return f"https://api.telegram.org/bot{token}/{method}"

    async def send(config: dict[str, Any], message: str) -> None:
        credential_type, credential_key = credentials_of(config)
        token = (
            await credentials(
                workspace_id=str(config["workspace_id"]),
                owner=str(config["owner"]),
                credential_type=credential_type,
                credential_key=credential_key,
            )
        ).get("bot_token")
        if not token:
            raise FatalError("the source's credentials have no bot_token")
        target = config.get("target") or {}
        chat_id = target.get("chat_id")
        if chat_id is None:
            raise FatalError("the delivery address has no chat_id")
        task_id = config.get("task_id")
        event_type = canonical_type(config.get("event_type", ""))
        permanent_errors = reply_of(config).permanent_errors
        line = (message or "").strip()

        key = f"tg:live:{task_id}"
        state = await _redis.hgetall(key)
        feed: list[str] = json.loads(state["feed"]) if state.get("feed") else []
        msg_id: str | None = state.get("message_id")

        if event_type in _terminal:
            feed = [line] if line else ["Done"]
        elif line and (not feed or feed[-1] != line):
            feed.append(line)
        text = "\n".join(feed) if feed else line
        if not text:
            return
        if len(text) > 4096:
            text = "…\n" + text[-4093:]

        try:
            async with outbound_client(Destination.VENDOR, timeout=10.0) as client:
                if not msg_id:
                    payload: dict[str, Any] = {
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "MarkdownV2",
                    }
                    reply_to = target.get("message_id")
                    if reply_to:
                        # A stale or deleted message to answer must not fail the reply.
                        payload["reply_to_message_id"] = reply_to
                        payload["allow_sending_without_reply"] = True
                    resp = await client.post(_api(token, "sendMessage"), json=payload)
                    if resp.status_code == 400 and "parse" in resp.text.lower():
                        payload["text"] = strip_markup(text)
                        payload.pop("parse_mode", None)
                        resp = await client.post(_api(token, "sendMessage"), json=payload)
                    raise_for_reply(resp, permanent_errors)
                    new_id = (resp.json().get("result") or {}).get("message_id")
                    if new_id:
                        await _redis.hset(
                            key, mapping={"message_id": str(new_id), "feed": json.dumps(feed)}
                        )
                        await _redis.expire(key, 3600)
                else:
                    payload = {
                        "chat_id": chat_id,
                        "message_id": int(msg_id),
                        "text": text,
                        "parse_mode": "MarkdownV2",
                    }
                    resp = await client.post(_api(token, "editMessageText"), json=payload)
                    body = resp.text.lower()
                    if resp.status_code == 400 and "not modified" in body:
                        resp = None
                    elif resp.status_code == 400 and "parse" in body:
                        payload["text"] = strip_markup(text)
                        payload.pop("parse_mode", None)
                        resp = await client.post(_api(token, "editMessageText"), json=payload)
                    if resp is not None:
                        raise_for_reply(resp, permanent_errors)
                    await _redis.hset(key, mapping={"feed": json.dumps(feed)})
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableError(f"network: {exc}") from exc
        except httpx.HTTPError as exc:
            raise RetryableError(f"http error: {exc}") from exc

        if event_type in _terminal:
            await _redis.delete(key)

    return send


# ── Registration ──────────────────────────────────────────────────


def register_all_adapters(
    secret_reader: SecretReader, credentials: CredentialReader, redis_url: str
) -> None:
    """Register every reply sender under the name addresses and targets give.

    ``credentials`` reads a source's credentials for the senders that answer
    where an event came from; ``secret_reader`` the per-task secrets of A2A
    push and task webhooks. Both are required: a sender without its store
    would drop replies.
    """
    register_adapter("http", HttpReplyAdapter(credentials))
    register_adapter(
        "telegram_live",
        _ComposedAdapter(
            formatter=_telegram_live_format,
            sender=make_telegram_live_sender(credentials, redis_url),
        ),
    )
    create_email_adapter(credentials)
    register_adapter("a2a_webhook", make_a2a_webhook_adapter(secret_reader))
    register_adapter("task_webhook", make_task_webhook_adapter(secret_reader))
