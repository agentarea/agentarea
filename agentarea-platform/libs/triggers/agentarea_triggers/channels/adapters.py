"""Composable channel adapter factories.

Instead of one class per channel, adapters are assembled from:
  - A formatter: (event, presentation) → str
  - A sender:    (channel_config, message) → None

Formatters are built from a markdown flavor config.
Senders are built from HTTP endpoint config.
Channels that need truly custom logic (Email/SMTP, Telegram retry)
provide their own functions and compose normally.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from . import register_adapter
from .exceptions import FatalError, RetryableError

if TYPE_CHECKING:
    from .secret_reader import SecretReader

logger = logging.getLogger(__name__)


# ── Markdown flavors ──────────────────────────────────────────────


@dataclass(frozen=True)
class MarkdownFlavor:
    """How to render bold/italic/quote + emoji map."""

    bold: tuple[str, str]  # (open, close) e.g. ("*", "*") or ("**", "**")
    italic: tuple[str, str]
    quote: str  # line prefix for quotes
    emojis: dict[str, str]  # logical name → rendered emoji
    escape: Callable[[str], str] | None = None  # optional text escaper


SLACK_EMOJIS = {
    "check": ":white_check_mark:",
    "cross": ":x:",
    "stop": ":no_entry_sign:",
    "question": ":question:",
    "hourglass": ":hourglass_flowing_sand:",
    "wrench": ":wrench:",
    "robot": ":robot_face:",
    "info": ":information_source:",
}

UNICODE_EMOJIS = {
    "check": "\u2705",
    "cross": "\u274c",
    "stop": "\u26d4",
    "question": "\u2753",
    "hourglass": "\u23f3",
    "wrench": "\U0001f527",
    "robot": "\U0001f916",
    "info": "\u2139\ufe0f",
}


def _telegram_escape(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!\\"
    return "".join("\\" + c if c in special else c for c in text)


SLACK_MD = MarkdownFlavor(
    bold=("*", "*"),
    italic=("_", "_"),
    quote=">",
    emojis=SLACK_EMOJIS,
)

DISCORD_MD = MarkdownFlavor(
    bold=("**", "**"),
    italic=("*", "*"),
    quote="> ",
    emojis=UNICODE_EMOJIS,
)

TELEGRAM_MD = MarkdownFlavor(
    bold=("*", "*"),
    italic=("_", "_"),
    quote=">",
    emojis=UNICODE_EMOJIS,
    escape=_telegram_escape,
)


# ── Formatter factory ─────────────────────────────────────────────


def make_formatter(flavor: MarkdownFlavor) -> Callable[[dict[str, Any], str], str]:
    """Build a format(event, presentation) function from a markdown flavor."""
    b0, b1 = flavor.bold
    i0, i1 = flavor.italic
    e = flavor.emojis
    esc = flavor.escape or (lambda t: t)

    def fmt(event: dict[str, Any], presentation: str) -> str:
        et = event.get("event_type", "")
        d = event.get("data", {})

        if et == "WorkflowCompleted":
            return esc(str(d.get("result") or d.get("final_response") or ""))
        if et == "WorkflowFailed":
            return f"{e['cross']} {b0}Failed{b1} \u2014 {esc(str(d.get('error', 'Unknown error')))}"
        if et == "WorkflowCancelled":
            return f"{e['stop']} {esc('Task was cancelled.')}"
        if et == "HumanApprovalRequested":
            q = esc(str(d.get("question", "Approval needed")))
            return f"{e['question']} {b0}Needs your input:{b1}\n{flavor.quote}{q}"
        if et == "HumanApprovalReceived":
            return f"{e['check']} {esc('Approval received, continuing...')}"

        if presentation == "concise":
            if et == "WorkflowStarted":
                return f"{e['hourglass']} {esc('Working on it...')}"
            if et == "ToolCallStarted":
                tool = d.get("tool_name", "tool")
                return f"{e['wrench']} {esc('Using ')}{i0}{esc(tool)}{i1}{esc('...')}"
            if et in ("AgentDelegationStarted", "AgentDelegationCompleted"):
                agent = d.get("agent_name", "sub-agent")
                action = "Delegating to" if "Started" in et else "Received from"
                return f"{e['robot']} {action} {i0}{esc(agent)}{i1}"

        return f"{e['info']} {esc(et)}"

    return fmt


# ── HTTP sender factory ───────────────────────────────────────────


@dataclass(frozen=True)
class HttpSenderConfig:
    """Config for building an HTTP-based send function."""

    url: str | Callable[[dict[str, Any], str], str]
    auth_fmt: str  # "Bearer {token}" or "Bot {token}"
    build_payload: Callable[[dict[str, Any], str], dict[str, Any]]
    max_length: int = 3000
    truncation_suffix: str = "\n\n_(truncated)_"
    validate_response: Callable[[httpx.Response], bool] = lambda r: r.is_success
    should_retry_plain: Callable[[httpx.Response], bool] = lambda _r: False
    build_plain_payload: Callable[[dict[str, Any], str], dict[str, Any]] | None = None


def make_http_sender(
    cfg: HttpSenderConfig,
    secret_reader: SecretReader,
) -> Callable[[dict[str, Any], str], Awaitable[None]]:
    """Build an async send(channel_config, message) function."""

    async def send(channel_config: dict[str, Any], message: str) -> None:
        token = await _resolve_token(secret_reader, channel_config)
        if not token:
            # No credentials = fatal misconfiguration; not retryable.
            raise FatalError("missing channel credentials")

        if len(message) > cfg.max_length:
            message = message[: cfg.max_length - len(cfg.truncation_suffix)] + cfg.truncation_suffix

        url = cfg.url(channel_config, token) if callable(cfg.url) else cfg.url
        payload = cfg.build_payload(channel_config, message)
        auth = cfg.auth_fmt.format(token=token)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": auth, "Content-Type": "application/json"},
                )
                if (
                    not cfg.validate_response(resp)
                    and cfg.build_plain_payload
                    and cfg.should_retry_plain(resp)
                ):
                    plain_payload = cfg.build_plain_payload(channel_config, message)
                    resp = await client.post(
                        url,
                        json=plain_payload,
                        headers={"Authorization": auth, "Content-Type": "application/json"},
                    )
                if not cfg.validate_response(resp):
                    _raise_for_response(resp)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
            raise RetryableError(f"network: {exc}") from exc
        except httpx.HTTPError as exc:
            # Other httpx errors (e.g. protocol issues) — treat as transient.
            raise RetryableError(f"http error: {exc}") from exc

    return send


def _raise_for_response(resp: httpx.Response) -> None:
    """Classify a non-success HTTP response into RetryableError vs FatalError.

    5xx + 429 = transient (broker should redeliver). 4xx = fatal (auth,
    blocked user, malformed payload — retrying won't fix it).
    """
    status = resp.status_code
    body = resp.text[:200] if resp.text else ""
    if status == 429:
        retry_after_hdr = resp.headers.get("Retry-After")
        retry_after: float | None = None
        if retry_after_hdr:
            try:
                retry_after = float(retry_after_hdr)
            except ValueError:
                retry_after = None
        raise RetryableError(f"rate limited: {body}", retry_after=retry_after)
    if 500 <= status < 600:
        raise RetryableError(f"upstream {status}: {body}")
    raise FatalError(f"upstream {status}: {body}")


def _strip_markdown(text: str) -> str:
    """Remove lightweight markdown/escape markers for plain-text fallback."""
    for marker in ("\\", "*", "_", "`"):
        text = text.replace(marker, "")
    return text


async def _resolve_token(
    secret_reader: SecretReader,
    channel_config: dict[str, Any],
) -> str | None:
    """Resolve bot token from the secret store. Shared by all HTTP senders.

    Returns None when the credential is genuinely absent or unreadable;
    `make_http_sender` translates that into `FatalError` so the message
    DLQs cleanly. We never raise from here because the secret reader is
    required at boot and a None result means "creds missing" — a
    classification, not a system failure.
    """
    trigger_id = channel_config.get("trigger_id")
    if not trigger_id:
        logger.error("No trigger_id in channel_config")
        return None

    ch_type = channel_config.get("type", "unknown")
    secret_name = f"channel_cred:{ch_type}:{trigger_id}"
    raw = await secret_reader.get_secret(secret_name)
    if not raw:
        logger.error("Credentials not found for %s trigger %s", ch_type, trigger_id)
        return None

    try:
        creds = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Stored blob is corrupt — caller will surface as FatalError.
        logger.error("Corrupt credentials blob for %s trigger %s: %s", ch_type, trigger_id, exc)
        return None
    return creds.get("bot_token")


# ── Channel definitions (just config) ─────────────────────────────

SLACK_SENDER = HttpSenderConfig(
    url="https://slack.com/api/chat.postMessage",
    auth_fmt="Bearer {token}",
    build_payload=lambda cfg, msg: {
        "channel": cfg["channel_id"],
        "text": msg,
        "mrkdwn": True,
        **({"thread_ts": cfg["thread_ts"]} if cfg.get("thread_ts") else {}),
    },
    max_length=3000,
    validate_response=lambda r: r.is_success and r.json().get("ok", False),
)

DISCORD_SENDER = HttpSenderConfig(
    url=lambda cfg, _token: f"https://discord.com/api/v10/channels/{cfg['channel_id']}/messages",
    auth_fmt="Bot {token}",
    build_payload=lambda cfg, msg: {
        "content": msg,
        **(
            {"message_reference": {"message_id": cfg["message_id"]}}
            if cfg.get("message_id")
            else {}
        ),
    },
    max_length=2000,
)

TELEGRAM_SENDER = HttpSenderConfig(
    url=lambda _cfg, token: f"https://api.telegram.org/bot{token}/sendMessage",
    auth_fmt="",  # token is in URL, not header
    build_payload=lambda cfg, msg: {
        "chat_id": cfg["chat_id"],
        "text": msg,
        "parse_mode": "MarkdownV2",
        **({"reply_to_message_id": cfg["message_id"]} if cfg.get("message_id") else {}),
    },
    max_length=4096,
    truncation_suffix="\n\n_\\(truncated\\)_",
    should_retry_plain=lambda r: r.status_code == 400 and "parse" in r.text.lower(),
    build_plain_payload=lambda cfg, msg: {
        "chat_id": cfg["chat_id"],
        "text": _strip_markdown(msg),
        **({"reply_to_message_id": cfg["message_id"]} if cfg.get("message_id") else {}),
    },
)


# ── Adapter wrapper ───────────────────────────────────────────────


class _ComposedAdapter:
    """Wraps a (formatter, sender) pair into the ChannelAdapter protocol."""

    def __init__(
        self,
        formatter: Callable[[dict[str, Any], str], str],
        sender: Callable[[dict[str, Any], str], Awaitable[None]],
    ):
        self._format = formatter
        self._send = sender

    def format(self, event: dict[str, Any], presentation: str) -> str:
        return self._format(event, presentation)

    async def send(self, channel_config: dict[str, Any], message: str) -> None:
        await self._send(channel_config, message)


# ── A2A push webhook adapter ──────────────────────────────────────


def _a2a_webhook_format(event: dict[str, Any], presentation: str) -> str:
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
        from agentarea_common.utils.url_safety import UnsafeUrlError, validate_outbound_url

        url = channel_config.get("url")
        if not url or not message:
            return
        try:
            validate_outbound_url(url)
        except UnsafeUrlError as e:
            # Misconfigured/hostile target — do not retry.
            raise FatalError(f"unsafe push webhook url: {e}") from e

        headers = {"Content-Type": "application/json"}
        task_id = channel_config.get("task_id")
        config_id = channel_config.get("config_id")
        if task_id and config_id:
            token = await secret_reader.get_secret(push_token_secret_name(task_id, config_id))
            if token:
                headers["X-A2A-Notification-Token"] = token

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, content=message, headers=headers)
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


# ── Registration ──────────────────────────────────────────────────


def register_all_adapters(secret_reader: SecretReader) -> None:
    """Register all HTTP-based channel adapters.

    `secret_reader` is required — channel delivery without a credential
    store would silently no-op, which is exactly the bug class this whole
    pipeline rewrite was built to remove. Missing the dep is a boot
    failure, not a runtime fallback.
    """
    channels = {
        "slack": (SLACK_MD, SLACK_SENDER),
        "discord": (DISCORD_MD, DISCORD_SENDER),
        "telegram": (TELEGRAM_MD, TELEGRAM_SENDER),
    }
    for name, (flavor, sender_cfg) in channels.items():
        adapter = _ComposedAdapter(
            formatter=make_formatter(flavor),
            sender=make_http_sender(sender_cfg, secret_reader),
        )
        register_adapter(name, adapter)

    # A2A push notifications: client-supplied webhooks, delivered as A2A events.
    register_adapter("a2a_webhook", make_a2a_webhook_adapter(secret_reader))
