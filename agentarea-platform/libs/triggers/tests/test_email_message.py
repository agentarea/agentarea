"""Normalizing an inbound email into a channel event.

Both inbound paths (a provider POSTing to our webhook, and polling an IMAP
mailbox) go through this module, so a reply threads the same way no matter how
the message arrived.
"""

import pytest
from agentarea_triggers.channels.email_message import (
    build_email_channel_origin,
    normalize_email,
    reply_subject,
    thread_key,
)


class TestNormalizeEmail:
    def test_reads_the_canonical_field_names(self):
        body = {
            "from": "alice@example.com",
            "to": "agent@agentarea.test",
            "subject": "Deploy failed",
            "text": "please look",
            "html": "<p>please look</p>",
            "message_id": "<m1@example.com>",
            "in_reply_to": "",
            "references": "",
        }

        msg = normalize_email(body, {})

        assert msg["from"] == "alice@example.com"
        assert msg["to"] == "agent@agentarea.test"
        assert msg["subject"] == "Deploy failed"
        assert msg["text"] == "please look"
        assert msg["message_id"] == "<m1@example.com>"

    def test_a_field_map_renames_without_touching_code(self):
        """Providers name these differently; that is configuration, not a branch."""
        body = {"FromFull": "bob@example.com", "TextBody": "hi", "Subject": "Q"}

        msg = normalize_email(
            body, {"from": "FromFull", "text": "TextBody", "subject": "Subject"}
        )

        assert msg["from"] == "bob@example.com"
        assert msg["text"] == "hi"
        assert msg["subject"] == "Q"

    def test_a_field_map_reaches_into_nested_payloads(self):
        body = {"From": {"Name": "Alice", "Address": "alice@example.com"}}

        msg = normalize_email(body, {"from": "From.Address"})

        assert msg["from"] == "alice@example.com"

    def test_a_list_of_recipients_collapses_to_addresses(self):
        body = {"To": [{"Address": "agent@agentarea.test"}, {"Address": "cc@x.test"}]}

        msg = normalize_email(body, {"to": "To[].Address"})

        assert msg["to"] == "agent@agentarea.test"
        assert msg["to_all"] == ["agent@agentarea.test", "cc@x.test"]

    def test_references_become_a_list_in_order(self):
        body = {"references": "<root@x> <second@x>", "message_id": "<third@x>"}

        msg = normalize_email(body, {})

        assert msg["references"] == ["<root@x>", "<second@x>"]

    def test_a_missing_field_is_absent_not_invented(self):
        msg = normalize_email({"from": "a@b.test"}, {})

        assert msg["subject"] is None
        assert msg["text"] is None
        assert msg["references"] == []

    def test_message_ids_normalize_to_their_rfc_form(self):
        """Some JSON APIs strip the angle brackets; the same mail must key alike."""
        bare = normalize_email(
            {"message_id": "root@x", "references": "parent@x"}, {}
        )
        bracketed = normalize_email(
            {"message_id": "<root@x>", "references": "<parent@x>"}, {}
        )

        assert bare["message_id"] == bracketed["message_id"] == "<root@x>"
        assert bare["references"] == bracketed["references"] == ["<parent@x>"]

    def test_a_body_that_is_not_an_object_is_rejected(self):
        with pytest.raises(ValueError, match="object"):
            normalize_email("not json", {})


class TestThreadKey:
    def test_the_root_of_references_wins(self):
        """Every message in a thread must land on the same key, including forks."""
        key = thread_key(
            message_id="<third@x>",
            in_reply_to="<second@x>",
            references=["<root@x>", "<second@x>"],
        )

        assert key == "<root@x>"

    def test_falls_back_to_in_reply_to_when_references_are_absent(self):
        key = thread_key(message_id="<second@x>", in_reply_to="<root@x>", references=[])

        assert key == "<root@x>"

    def test_a_first_message_keys_on_its_own_id(self):
        key = thread_key(message_id="<root@x>", in_reply_to=None, references=[])

        assert key == "<root@x>"

    def test_a_message_with_no_id_at_all_has_no_thread(self):
        """Without a Message-ID there is nothing stable to thread on."""
        assert thread_key(message_id=None, in_reply_to=None, references=[]) is None


class TestReplySubject:
    def test_prefixes_once(self):
        assert reply_subject("Deploy failed") == "Re: Deploy failed"

    def test_does_not_stack_prefixes(self):
        assert reply_subject("Re: Deploy failed") == "Re: Deploy failed"
        assert reply_subject("RE: Deploy failed") == "RE: Deploy failed"

    def test_a_missing_subject_still_produces_one(self):
        assert reply_subject(None) == "Re: (no subject)"


class TestBuildEmailChannelOrigin:
    def test_carries_everything_the_reply_needs(self):
        msg = {
            "from": "alice@example.com",
            "to": "agent@agentarea.test",
            "subject": "Deploy failed",
            "message_id": "<m1@example.com>",
            "in_reply_to": None,
            "references": [],
            "text": "please look",
        }

        origin = build_email_channel_origin(msg, trigger_id="trig-1")

        assert origin["type"] == "email"
        assert origin["trigger_id"] == "trig-1"
        assert origin["reply_to"] == "alice@example.com"
        assert origin["subject"] == "Re: Deploy failed"
        assert origin["message_id"] == "<m1@example.com>"
        assert origin["chat_id"] == "<m1@example.com>"
        assert origin["presentation"] == "concise"

    def test_a_follow_up_reuses_the_thread_key(self):
        """This is what routes a reply into the running task instead of a new one."""
        first = build_email_channel_origin(
            {
                "from": "alice@example.com",
                "subject": "Deploy failed",
                "message_id": "<root@x>",
                "in_reply_to": None,
                "references": [],
            },
            trigger_id="trig-1",
        )
        follow_up = build_email_channel_origin(
            {
                "from": "alice@example.com",
                "subject": "Re: Deploy failed",
                "message_id": "<second@x>",
                "in_reply_to": "<root@x>",
                "references": ["<root@x>"],
            },
            trigger_id="trig-1",
        )

        assert follow_up["chat_id"] == first["chat_id"]

    def test_references_accumulate_for_the_reply_header(self):
        origin = build_email_channel_origin(
            {
                "from": "alice@example.com",
                "message_id": "<second@x>",
                "in_reply_to": "<root@x>",
                "references": ["<root@x>"],
            },
            trigger_id="trig-1",
        )

        assert origin["references"] == ["<root@x>", "<second@x>"]

    def test_no_sender_means_no_outbound_route(self):
        """Nowhere to reply to is not a channel — say so instead of half-building one."""
        origin = build_email_channel_origin(
            {"subject": "x", "message_id": "<m@x>", "references": []}, trigger_id="trig-1"
        )

        assert origin is None
