"""Polling a connected mailbox.

The extractor never touches message flags — the mailbox belongs to the user,
not to us — so the cursor is a UID, not the read/unread state.
"""

from email.message import EmailMessage

import pytest
from agentarea_triggers.extractors import get_extractor
from agentarea_triggers.extractors.imap import ImapExtractor


def raw_mail(
    *,
    sender="alice@example.com",
    to="agent@agentarea.test",
    subject="Deploy failed",
    body="please look",
    message_id="<m1@example.com>",
    in_reply_to=None,
    references=None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(references)
    msg.set_content(body)
    return msg.as_bytes()


class FakeImap:
    """Just enough of imaplib.IMAP4 for the extractor."""

    def __init__(self, messages: dict[int, bytes]):
        self.messages = messages
        self.logged_in_as = None
        self.selected = None
        self.readonly = None
        self.searches: list[str] = []
        self.logged_out = False

    def login(self, user, password):
        self.logged_in_as = (user, password)
        return ("OK", [b""])

    def select(self, mailbox, readonly=False):
        self.selected = mailbox
        self.readonly = readonly
        return ("OK", [b"1"])

    def uid(self, command, *args):
        if command == "SEARCH":
            criteria = args[-1]
            self.searches.append(criteria)
            lo = 1
            if criteria.startswith("UID "):
                lo = int(criteria.split()[1].split(":")[0])
            hits = sorted(uid for uid in self.messages if uid >= lo)
            return ("OK", [" ".join(str(u) for u in hits).encode()])
        if command == "FETCH":
            uid = int(args[0])
            return ("OK", [(b"1 (RFC822 {})", self.messages[uid])])
        raise AssertionError(f"unexpected command {command}")

    def logout(self):
        self.logged_out = True


def build(messages, *, creds='{"username": "u", "password": "p"}'):
    class Reader:
        async def get_secret(self, name):
            Reader.asked_for = name
            return creds

    fake = FakeImap(messages)
    extractor = ImapExtractor(secret_reader=Reader(), connect=lambda **kw: fake)
    return extractor, fake, Reader


CONFIG = {"host": "imap.example.com", "trigger_id": "11111111-1111-1111-1111-111111111111"}


class TestFirstPoll:
    async def test_does_not_replay_the_existing_mailbox(self):
        """Connecting a ten-year-old mailbox must not dump it onto the agent."""
        extractor, _, _ = build({1: raw_mail(), 2: raw_mail(), 7: raw_mail()})

        result = await extractor.extract(CONFIG, None)

        assert result.has_new_data is False
        assert result.events == []
        assert result.updated_state == {"last_uid": 7}

    async def test_an_empty_mailbox_starts_at_zero(self):
        extractor, _, _ = build({})

        result = await extractor.extract(CONFIG, None)

        assert result.updated_state == {"last_uid": 0}


class TestSubsequentPolls:
    async def test_returns_the_oldest_unseen_message(self):
        extractor, _, _ = build({5: raw_mail(subject="first"), 6: raw_mail(subject="second")})

        result = await extractor.extract(CONFIG, {"last_uid": 4})

        assert result.has_new_data is True
        assert len(result.events) == 1
        assert result.events[0]["subject"] == "first"
        assert result.updated_state["last_uid"] == 5

    async def test_reports_what_is_still_waiting(self):
        """One task per poll is the downstream contract; say what is queued."""
        extractor, _, _ = build({5: raw_mail(), 6: raw_mail(), 7: raw_mail()})

        result = await extractor.extract(CONFIG, {"last_uid": 4})

        assert result.updated_state["pending"] == 2

    async def test_no_new_mail_leaves_the_cursor_alone(self):
        extractor, _, _ = build({5: raw_mail()})

        result = await extractor.extract(CONFIG, {"last_uid": 5})

        assert result.has_new_data is False
        assert result.updated_state == {"last_uid": 5, "pending": 0}

    async def test_searches_forward_from_the_cursor(self):
        extractor, fake, _ = build({5: raw_mail()})

        await extractor.extract(CONFIG, {"last_uid": 4})

        assert fake.searches == ["UID 5:*"]


class TestNormalization:
    async def test_produces_the_same_shape_as_the_webhook_path(self):
        extractor, _, _ = build({5: raw_mail(subject="Deploy failed", body="please look")})

        result = await extractor.extract(CONFIG, {"last_uid": 4})
        event = result.events[0]

        assert event["from"] == "alice@example.com"
        assert event["to"] == "agent@agentarea.test"
        assert event["subject"] == "Deploy failed"
        assert event["text"].strip() == "please look"
        assert event["message_id"] == "<m1@example.com>"

    async def test_a_reply_carries_the_thread_of_the_original(self):
        extractor, _, _ = build(
            {
                5: raw_mail(
                    message_id="<second@x>",
                    in_reply_to="<root@x>",
                    references=["<root@x>"],
                )
            }
        )

        result = await extractor.extract(CONFIG, {"last_uid": 4})

        assert result.channel_origin["chat_id"] == "<root@x>"
        assert result.channel_origin["type"] == "email"
        assert result.channel_origin["reply_to"] == "alice@example.com"


class TestMailboxSafety:
    async def test_opens_the_mailbox_read_only(self):
        """Polling must not mark the user's mail as read behind their back."""
        extractor, fake, _ = build({5: raw_mail()})

        await extractor.extract(CONFIG, {"last_uid": 4})

        assert fake.readonly is True
        assert fake.selected == "INBOX"

    async def test_logs_out_even_when_parsing_blows_up(self):
        extractor, fake, _ = build({5: b"\xff\xfe not a message at all"})

        await extractor.extract(CONFIG, {"last_uid": 4})

        assert fake.logged_out is True


class TestConfiguration:
    async def test_credentials_come_from_the_secret_store(self):
        extractor, fake, reader = build({5: raw_mail()})

        await extractor.extract(CONFIG, {"last_uid": 4})

        assert reader.asked_for == "channel_cred:imap:11111111-1111-1111-1111-111111111111"
        assert fake.logged_in_as == ("u", "p")

    async def test_a_missing_host_fails_loudly(self):
        extractor, _, _ = build({})

        with pytest.raises(ValueError, match="host"):
            await extractor.extract({"trigger_id": "t1"}, None)

    async def test_a_missing_trigger_id_fails_loudly(self):
        """Without it there is no way to find the mailbox credentials."""
        extractor, _, _ = build({})

        with pytest.raises(ValueError, match="trigger_id"):
            await extractor.extract({"host": "imap.example.com"}, None)

    async def test_unreadable_credentials_fail_loudly(self):
        extractor, _, _ = build({}, creds=None)

        with pytest.raises(ValueError, match="credentials"):
            await extractor.extract(CONFIG, None)

    async def test_credentials_without_a_password_fail_loudly(self):
        extractor, _, _ = build({}, creds='{"username": "u"}')

        with pytest.raises(ValueError, match="password"):
            await extractor.extract(CONFIG, None)


class TestRegistration:
    def test_registers_itself_under_imap(self):
        assert get_extractor("imap") is ImapExtractor
