"""Who may talk to an agent through a messenger: the catalog entry's ``admission``.

An event whose source type has an ``admission`` block is let through only for a
sender linked to a platform user. Today the one identity the platform links is
Telegram's, so the link handshake and the notices below speak the Bot API.

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
from collections.abc import Awaitable, Callable, Mapping
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
from agentarea_common.outbound import Destination, outbound_client
from agentarea_streams.application.source_credentials import credential_secret_name
from agentarea_streams.domain import StreamEvent
from agentarea_streams.domain.source_types import Admission
from agentarea_streams.domain.templates import TemplateContext, render_first
from agentarea_streams.infrastructure.catalog_source_types import CatalogSourceTypeRepository
from agentarea_streams.infrastructure.orm import StreamSourceORM
from sqlalchemy.ext.asyncio import AsyncSession

from .secret_reader import SecretReader

logger = logging.getLogger(__name__)

LINK_COMMAND = "/start link_"
CONFIRM_COMMAND = "/confirm"
#: An unlinked or refused sender hears why at most once per this many seconds.
NOTICE_INTERVAL_SECONDS = 86400

MayRun = Callable[..., Awaitable[bool]]


#: The trigger a message arrived through. Only ``id``, ``workspace_id`` and
#: ``agent_id`` are read.
_Trigger = Any


@dataclass(frozen=True)
class TelegramSender:
    """The sender of one message, as the entry's admission templates read it."""

    external_id: str
    chat_id: str
    private: bool
    is_bot: bool
    text: str

    @classmethod
    def from_event(
        cls, admission: Admission, body: Any, headers: Mapping[str, str]
    ) -> TelegramSender | None:
        """The sender of an event; ``None`` if it names none."""
        context = TemplateContext(body=body, headers=headers)
        external_id = render_first(admission.external_id, context)
        chat_id = render_first(admission.chat, context)
        if external_id is None or chat_id is None:
            return None
        return cls(
            external_id=external_id,
            chat_id=chat_id,
            private=render_first(admission.private, context) == admission.private_value,
            is_bot=render_first(admission.is_bot, context) == "true",
            text=(render_first(admission.text, context) or "").strip(),
        )


@dataclass(frozen=True)
class EventAdmission:
    """The admission an event's source type asks for, and where its bot's credentials are."""

    admission: Admission
    credentials_secret: str


async def event_admission(session: AsyncSession, event: StreamEvent) -> EventAdmission | None:
    """What admits the sender of ``event``; None when its source type admits anyone.

    Raises ``LookupError`` when the event names a source or type that cannot be
    read: a door that cannot be checked stays shut.
    """
    if event.source_id is None:
        return None
    source = await session.get(StreamSourceORM, event.source_id)
    if source is None or source.workspace_id != event.workspace_id:
        raise LookupError(f"source {event.source_id} of event {event.id} is gone")
    slug = source.webhook_type or ""
    entry = await CatalogSourceTypeRepository(session).get(slug)
    if entry is None:
        raise LookupError(f"source type {slug!r} of event {event.id} is not in the catalog")
    if entry.admission is None:
        return None
    if source.credential_key is None:
        raise LookupError(f"source {source.id} has no credentials")
    return EventAdmission(
        admission=entry.admission,
        credentials_secret=credential_secret_name(slug, source.credential_key),
    )


@dataclass(frozen=True)
class _BotOf:
    """The bot that answers a sender: the one whose token the source stores."""

    credentials_secret: str


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
        async with outbound_client(Destination.VENDOR, timeout=10.0) as client:
            response = await client.get(f"{self._base}/getMe")
        if not response.is_success:
            logger.warning("Telegram getMe failed: %s", response.status_code)
            return None
        return (response.json().get("result") or {}).get("username")

    async def send(self, chat_id: str, text: str) -> None:
        async with outbound_client(Destination.VENDOR, timeout=10.0) as client:
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
        self, session: AsyncSession, trigger: _Trigger, event: StreamEvent, door: EventAdmission
    ) -> Admitted | Refused:
        if door.admission.identity != TELEGRAM:
            return Refused(f"no sender admission links {door.admission.identity} accounts")
        data = event.data if isinstance(event.data, Mapping) else {}
        headers = data.get("headers")
        sender = TelegramSender.from_event(
            door.admission, data.get("body"), headers if isinstance(headers, Mapping) else {}
        )
        bot = _BotOf(door.credentials_secret)
        if sender is None:
            return Refused("the update names no sender")
        if sender.is_bot:
            return Refused("the sender is a bot")
        if not sender.private:
            return Refused("only private chats reach the agent")

        if sender.text.startswith(LINK_COMMAND):
            await self._redeem(bot, sender, sender.text[len(LINK_COMMAND) :].strip())
            return Refused("account link requested")
        if sender.text == CONFIRM_COMMAND:
            await self._confirm(session, bot, sender)
            return Refused("account link confirmation")

        user_id = await self._identities(session).holder(TELEGRAM, sender.external_id)
        if user_id is None:
            await self._notify_once(
                trigger, bot, sender, "unlinked", await self._unlinked_text(bot)
            )
            return Refused("the sender has not linked their Telegram account")
        if not await self._may_run(
            session,
            user_id=user_id,
            workspace_id=str(trigger.workspace_id),
            agent_id=trigger.agent_id,
        ):
            await self._notify_once(
                trigger,
                bot,
                sender,
                "denied",
                "Your account doesn't have access to this agent. Ask its owner to grant it.",
            )
            return Refused(f"user {user_id} may not run agent {trigger.agent_id}")
        return Admitted(user_id)

    async def _redeem(self, bot: _BotOf, sender: TelegramSender, code: str) -> None:
        user_id = (
            await self._link_codes.redeem(code, provider=TELEGRAM, external_id=sender.external_id)
            if code
            else None
        )
        if user_id is None:
            await self._reply(
                bot,
                sender,
                "This link has expired or was already used. Open the link page again "
                "for a new one.",
            )
            return
        who = await self._describe(user_id)
        await self._reply(
            bot,
            sender,
            f"Link this Telegram account to {who}? Send {CONFIRM_COMMAND} within 10 minutes. "
            "If you did not ask for this, ignore this message.",
        )

    async def _confirm(self, session: AsyncSession, bot: _BotOf, sender: TelegramSender) -> None:
        user_id = await self._link_codes.confirm(provider=TELEGRAM, external_id=sender.external_id)
        if user_id is None:
            await self._reply(bot, sender, "There is nothing to confirm.")
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
                bot,
                sender,
                "This Telegram account is already linked to another AgentArea account. "
                "Unlink it there first.",
            )
            return
        logger.info("Telegram account linked to user %s", user_id)
        await self._reply(
            bot,
            sender,
            f"Done: this Telegram account is linked to {await self._describe(user_id)}.",
        )

    async def _unlinked_text(self, bot: _BotOf) -> str:
        client = await self._bot(bot)
        username = await client.username() if client else None
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
        self, trigger: _Trigger, bot: _BotOf, sender: TelegramSender, kind: str, text: str
    ) -> None:
        if await self._notices.claim(f"{trigger.id}:{sender.external_id}:{kind}"):
            await self._reply(bot, sender, text)

    async def _reply(self, bot: _BotOf, sender: TelegramSender, text: str) -> None:
        client = await self._bot(bot)
        if client is None:
            return
        try:
            await client.send(sender.chat_id, text)
        except httpx.HTTPError:
            logger.warning("Could not reply to a Telegram sender", exc_info=True)

    async def _bot(self, bot: _BotOf) -> TelegramBotClient | None:
        raw = await self._secret_reader.get_secret(bot.credentials_secret)
        try:
            token = json.loads(raw).get("bot_token") if raw else None
        except json.JSONDecodeError:
            logger.error("The source's stored credentials are not JSON", exc_info=True)
            token = None
        if not token:
            logger.error("The source has no Telegram bot token")
            return None
        return self._bot_client_factory(token)


def build_telegram_sender_admission(
    *,
    may_run: MayRun,
    secret_reader: SecretReader,
    redis_url: str,
    namespace: str,
    app_url: str,
) -> TelegramSenderAdmission:
    return TelegramSenderAdmission(
        may_run=may_run,
        link_codes=LinkCodes(redis_url),
        notices=DedupCache(
            redis_url,
            namespace=namespace,
            prefix="telegram-sender-notice",
            ttl_seconds=NOTICE_INTERVAL_SECONDS,
        ),
        secret_reader=secret_reader,
        app_url=app_url,
    )
