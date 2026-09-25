"""Poll a connected IMAP mailbox for new mail.

This is the "I connected my own inbox" path, as opposed to the webhook path
where a provider pushes mail addressed to the agent. Both normalize through
``channels.email_message`` so a reply threads the same way either way.

Two deliberate constraints:

* The mailbox is opened READ-ONLY and progress is tracked by UID rather than by
  the seen flag. The mailbox belongs to the user; polling it must not silently
  mark their mail as read.
* One message per poll. Downstream, a trigger execution collapses every
  extracted event into a single task with a single ``channel_origin``, so
  emitting a batch would answer several senders at the address of whichever one
  happened to be last. Remaining mail is reported as ``pending`` and drains on
  the next tick.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import json
import logging
from email.policy import default as default_policy
from typing import Any

from ..channels.email_message import (
    build_email_channel_origin,
    canonical_message_id,
    parse_message_ids,
)
from . import ExtractionResult, register_extractor

logger = logging.getLogger(__name__)

DEFAULT_MAILBOX = "INBOX"
IMAPS_PORT = 993
IMAP_PORT = 143


def _connect_imap(*, host: str, port: int, use_ssl: bool) -> Any:
    if use_ssl:
        return imaplib.IMAP4_SSL(host, port)
    return imaplib.IMAP4(host, port)


def _default_secret_reader() -> Any:
    from agentarea_common.config.secrets import get_secret_manager_settings
    from agentarea_secrets import SecretManagerFactory

    from ..channels.lazy_secret_manager import LazySecretReader

    return LazySecretReader(SecretManagerFactory(get_secret_manager_settings()))


def _header(message: Any, name: str) -> str | None:
    value = message.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _body_text(message: Any) -> str | None:
    try:
        part = message.get_body(preferencelist=("plain", "html"))
    except Exception:
        part = None
    if part is None:
        return None
    try:
        content = part.get_content()
    except Exception:
        logger.exception("Could not decode the body of an inbound message")
        return None
    text = str(content).strip()
    return text or None


def _to_normalized(raw: bytes) -> dict[str, Any]:
    message = email.message_from_bytes(raw, policy=default_policy)
    return {
        "from": _header(message, "From"),
        "to": _header(message, "To"),
        "to_all": [t for t in [_header(message, "To")] if t],
        "subject": _header(message, "Subject"),
        "text": _body_text(message),
        "html": None,
        "message_id": canonical_message_id(_header(message, "Message-ID")),
        "in_reply_to": canonical_message_id(_header(message, "In-Reply-To")),
        "references": parse_message_ids(_header(message, "References")),
    }


class ImapExtractor:
    #: Credentials come from the secret store, so the API must not copy them
    #: into the plain-JSON ``data_extractor_config`` column.
    resolves_own_credentials = True
    reply_channel_type = "email"

    def __init__(self, secret_reader: Any = None, connect: Any = None) -> None:
        # Both parameters are test seams. At runtime the real reader is always
        # constructed, so there is never a None to check for at the use site.
        self._secret_reader = secret_reader or _default_secret_reader()
        self._connect = connect or _connect_imap

    async def extract(
        self, config: dict[str, Any], state: dict[str, Any] | None
    ) -> ExtractionResult:
        host = (config.get("host") or "").strip()
        if not host:
            raise ValueError("imap extractor: 'host' is required")

        trigger_id = (config.get("trigger_id") or "").strip()
        if not trigger_id:
            raise ValueError("imap extractor: 'trigger_id' is required to read credentials")

        username, password = await self._credentials(trigger_id)

        use_ssl = config.get("use_ssl", True)
        port = int(config.get("port") or (IMAPS_PORT if use_ssl else IMAP_PORT))
        mailbox = config.get("mailbox") or DEFAULT_MAILBOX
        last_uid = (state or {}).get("last_uid")

        return await asyncio.to_thread(
            self._poll,
            host=host,
            port=port,
            use_ssl=use_ssl,
            mailbox=mailbox,
            username=username,
            password=password,
            last_uid=last_uid,
            trigger_id=trigger_id,
        )

    async def _credentials(self, trigger_id: str) -> tuple[str, str]:
        name = f"channel_cred:imap:{trigger_id}"
        raw = await self._secret_reader.get_secret(name)
        if not raw:
            raise ValueError(f"imap extractor: mailbox credentials not found ({name})")
        try:
            creds = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"imap extractor: credentials for {name} are not valid JSON") from exc

        username = (creds.get("username") or "").strip()
        password = creds.get("password") or ""
        if not username:
            raise ValueError(f"imap extractor: credentials for {name} have no username")
        if not password:
            raise ValueError(f"imap extractor: credentials for {name} have no password")
        return username, password

    def _poll(
        self,
        *,
        host: str,
        port: int,
        use_ssl: bool,
        mailbox: str,
        username: str,
        password: str,
        last_uid: int | None,
        trigger_id: str,
    ) -> ExtractionResult:
        client = self._connect(host=host, port=port, use_ssl=use_ssl)
        try:
            client.login(username, password)
            client.select(mailbox, readonly=True)

            if last_uid is None:
                # First poll on a mailbox that already has history: start from
                # now. Replaying years of archived mail as agent tasks would be
                # both expensive and wrong.
                newest = self._search(client, 1)
                highest = newest[-1] if newest else 0
                logger.info(
                    "imap extractor: starting at uid %s for trigger %s", highest, trigger_id
                )
                return ExtractionResult(has_new_data=False, updated_state={"last_uid": highest})

            new_uids = self._search(client, last_uid + 1)
            if not new_uids:
                return ExtractionResult(
                    has_new_data=False, updated_state={"last_uid": last_uid, "pending": 0}
                )

            uid = new_uids[0]
            raw = self._fetch(client, uid)
            state = {"last_uid": uid, "pending": len(new_uids) - 1}
            if raw is None:
                # The cursor still advances: a message we cannot read would
                # otherwise block every later one forever.
                logger.error("imap extractor: could not fetch uid %s, skipping it", uid)
                return ExtractionResult(has_new_data=False, updated_state=state)

            try:
                message = _to_normalized(raw)
            except Exception:
                logger.exception("imap extractor: unparseable message at uid %s, skipping it", uid)
                return ExtractionResult(has_new_data=False, updated_state=state)

            origin = build_email_channel_origin(
                message, trigger_id=trigger_id, credential_type="imap"
            )
            return ExtractionResult(
                has_new_data=True,
                events=[{"event_type": "message_received", **message}],
                updated_state=state,
                channel_origin=origin or {},
            )
        finally:
            try:
                client.logout()
            except Exception:
                logger.warning("imap extractor: logout failed", exc_info=True)

    def _search(self, client: Any, from_uid: int) -> list[int]:
        status, data = client.uid("SEARCH", None, f"UID {from_uid}:*")
        if status != "OK" or not data or not data[0]:
            return []
        uids = sorted(int(part) for part in data[0].split())
        # "UID n:*" is inclusive of the highest uid even when it is below n, so
        # the server can hand back a message we have already processed.
        return [uid for uid in uids if uid >= from_uid]

    def _fetch(self, client: Any, uid: int) -> bytes | None:
        status, data = client.uid("FETCH", str(uid), "(RFC822)")
        if status != "OK" or not data:
            return None
        for part in data:
            if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], bytes):
                return part[1]
        return None


register_extractor("imap", ImapExtractor)
