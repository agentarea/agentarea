"""Who may talk to an agent through a Telegram bot.

A bot is a door: it answers "who is this?" and nothing more. The sender's
Telegram account resolves to a platform user only through a link the person
proved from inside Telegram (``agentarea_common.identity``), and that user is
admitted only when the graph lets them run the agent -- the same ``may_run``
that keeps a trigger's configurer honest. Everyone else is refused: an
unlinked sender is told once a day how to link, a linked one without access
is told they have none, and group chats and other bots are ignored.

The link handshake runs here too, before admission, because it is the one
thing an unlinked sender is allowed to do: ``/start link_<code>`` redeems a
code the signed-in user asked for, and ``/confirm`` from the same account
writes the link.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from agentarea_common.broker import DedupCache
from agentarea_common.identity import (
    ExternalIdentityRepository,
    ExternalIdentityTakenError,
    LinkCodes,
)
from agentarea_common.identity.models import METHOD_PAIRING, TELEGRAM
from sqlalchemy.ext.asyncio import AsyncSession

from .secret_reader import SecretReader

logger = logging.getLogger(__name__)

LINK_COMMAND = "/start link_"
CONFIRM_COMMAND = "/confirm"
#: An unlinked or refused sender hears why at most once per this many seconds.
NOTICE_INTERVAL_SECONDS = 86400

MayRun = Callable[..., Awaitable[bool]]


#: The trigger a message arrived through: the domain model on the webhook path,
#: the ORM row on the poller path. Only ``id``, ``workspace_id`` and ``agent_id``
#: are read.
_Trigger = Any


@dataclass(frozen=True)
class TelegramSender:
    """The sender of one Telegram message, as the update reports them."""

    external_id: str
    chat_id: str
    private: bool
    is_bot: bool
    text: str

    @classmethod
    def from_event(cls, data: dict[str, Any]) -> TelegramSender | None:
        """Read the sender from a webhook event or a polled one; ``None`` if it names none."""
        user_id = data.get("user_id")
        chat_id = data.get("chat_id")
        if user_id is None or chat_id is None:
            return None
        raw = data.get("raw_data") or data.get("raw") or {}
        message = (raw.get("message") or raw.get("edited_message") or {}) if raw else {}
        chat_type = data.get("chat_type") or (message.get("chat") or {}).get("type")
        # A private chat's id is the user's own id; the poller reports no chat type.
        private = chat_type == "private" if chat_type else str(chat_id) == str(user_id)
        return cls(
            external_id=str(user_id),
            chat_id=str(chat_id),
            private=private,
            is_bot=bool((message.get("from") or {}).get("is_bot")),
            text=str(data.get("text") or "").strip(),
        )


@dataclass(frozen=True)
class Admitted:
    user_id: str


@dataclass(frozen=True)
class Refused:
    reason: str


class TelegramBotClient:
    """The two Bot API calls the door needs, with the trigger's own token."""

    def __init__(self, token: str):
        self._base = f"https://api.telegram.org/bot{token}"

    async def username(self) -> str | None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base}/getMe")
        if not response.is_success:
            logger.warning("Telegram getMe failed: %s", response.status_code)
            return None
        return (response.json().get("result") or {}).get("username")

    async def send(self, chat_id: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self._base}/sendMessage", json={"chat_id": chat_id, "text": text}
            )
        if not response.is_success:
            logger.warning("Telegram sendMessage failed: %s", response.status_code)


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "your AgentArea account"
    return f"{local[:1]}***@{domain}"


class TelegramSenderAdmission:
    def __init__(
        self,
        *,
        may_run: MayRun,
        link_codes: LinkCodes,
        notices: DedupCache,
        secret_reader: SecretReader,
        app_url: str,
        bot_client_factory: Callable[[str], TelegramBotClient] = TelegramBotClient,
        identities: Callable[[AsyncSession], ExternalIdentityRepository] = (
            ExternalIdentityRepository
        ),
    ):
        self._may_run = may_run
        self._link_codes = link_codes
        self._notices = notices
        self._secret_reader = secret_reader
        self._app_url = app_url.rstrip("/")
        self._bot_client_factory = bot_client_factory
        self._identities = identities

    async def admit(
        self, session: AsyncSession, trigger: _Trigger, data: dict[str, Any]
    ) -> Admitted | Refused:
        sender = TelegramSender.from_event(data)
        if sender is None:
            return Refused("the update names no sender")
        if sender.is_bot:
            return Refused("the sender is a bot")
        if not sender.private:
            return Refused("only private chats reach the agent")

        if sender.text.startswith(LINK_COMMAND):
            await self._redeem(trigger, sender, sender.text[len(LINK_COMMAND) :].strip())
            return Refused("account link requested")
        if sender.text == CONFIRM_COMMAND:
            await self._confirm(session, trigger, sender)
            return Refused("account link confirmation")

        user_id = await self._identities(session).holder(TELEGRAM, sender.external_id)
        if user_id is None:
            await self._notify_once(trigger, sender, "unlinked", await self._unlinked_text(trigger))
            return Refused("the sender has not linked their Telegram account")
        if not await self._may_run(
            session,
            user_id=user_id,
            workspace_id=str(trigger.workspace_id),
            agent_id=trigger.agent_id,
        ):
            await self._notify_once(
                trigger,
                sender,
                "denied",
                "Your account doesn't have access to this agent. Ask its owner to grant it.",
            )
            return Refused(f"user {user_id} may not run agent {trigger.agent_id}")
        return Admitted(user_id)

    async def _redeem(self, trigger: _Trigger, sender: TelegramSender, code: str) -> None:
        user_id = (
            await self._link_codes.redeem(code, provider=TELEGRAM, external_id=sender.external_id)
            if code
            else None
        )
        if user_id is None:
            await self._reply(
                trigger,
                sender,
                "This link has expired or was already used. Open the link page again "
                "for a new one.",
            )
            return
        who = await self._describe(user_id)
        await self._reply(
            trigger,
            sender,
            f"Link this Telegram account to {who}? Send {CONFIRM_COMMAND} within 10 minutes. "
            "If you did not ask for this, ignore this message.",
        )

    async def _confirm(
        self, session: AsyncSession, trigger: _Trigger, sender: TelegramSender
    ) -> None:
        user_id = await self._link_codes.confirm(provider=TELEGRAM, external_id=sender.external_id)
        if user_id is None:
            await self._reply(trigger, sender, "There is nothing to confirm.")
            return
        try:
            await self._identities(session).link(
                user_id=user_id,
                provider=TELEGRAM,
                external_id=sender.external_id,
                method=METHOD_PAIRING,
            )
        except ExternalIdentityTakenError:
            await self._reply(
                trigger,
                sender,
                "This Telegram account is already linked to another AgentArea account. "
                "Unlink it there first.",
            )
            return
        logger.info("Telegram account linked to user %s", user_id)
        await self._reply(
            trigger,
            sender,
            f"Done: this Telegram account is linked to {await self._describe(user_id)}.",
        )

    async def _unlinked_text(self, trigger: _Trigger) -> str:
        bot = await self._bot(trigger)
        username = await bot.username() if bot else None
        url = f"{self._app_url}/link/telegram" + (f"?bot={username}" if username else "")
        return (
            "This bot answers only people who linked their Telegram account to AgentArea "
            f"and were given access. Link yours here: {url}"
        )

    async def _describe(self, user_id: str) -> str:
        from agentarea_common.auth.identity_directory import get_identity_directory

        directory = get_identity_directory()
        if directory is None:
            return "your AgentArea account"
        try:
            records = await directory.resolve([user_id])
        except Exception:
            logger.warning("Identity directory unavailable; not naming the account")
            return "your AgentArea account"
        record = records.get(user_id)
        return _mask_email(record.email) if record and record.email else "your AgentArea account"

    async def _notify_once(
        self, trigger: _Trigger, sender: TelegramSender, kind: str, text: str
    ) -> None:
        if await self._notices.claim(f"{trigger.id}:{sender.external_id}:{kind}"):
            await self._reply(trigger, sender, text)

    async def _reply(self, trigger: _Trigger, sender: TelegramSender, text: str) -> None:
        bot = await self._bot(trigger)
        if bot is None:
            return
        try:
            await bot.send(sender.chat_id, text)
        except httpx.HTTPError:
            logger.warning("Could not reply to a Telegram sender of trigger %s", trigger.id)

    async def _bot(self, trigger: _Trigger) -> TelegramBotClient | None:
        raw = await self._secret_reader.get_secret(f"channel_cred:telegram:{trigger.id}")
        try:
            token = json.loads(raw).get("bot_token") if raw else None
        except json.JSONDecodeError:
            token = None
        if not token:
            logger.error("Trigger %s has no Telegram bot token", trigger.id)
            return None
        return self._bot_client_factory(token)


def build_telegram_sender_admission(
    *, may_run: MayRun, secret_reader: SecretReader, redis_url: str, app_url: str
) -> TelegramSenderAdmission:
    return TelegramSenderAdmission(
        may_run=may_run,
        link_codes=LinkCodes(redis_url),
        notices=DedupCache(
            redis_url, prefix="telegram-sender-notice", ttl_seconds=NOTICE_INTERVAL_SECONDS
        ),
        secret_reader=secret_reader,
        app_url=app_url,
    )


def is_telegram_trigger(trigger: Any) -> bool:
    """A trigger whose events are Telegram messages: its webhook or its poller."""
    if str(getattr(trigger, "webhook_type", "") or "") == "telegram":
        return True
    return str(getattr(trigger, "data_extractor", "") or "") == "telegram_polling"
