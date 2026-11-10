"""A connector can declare how the agent's arguments become the request a vendor expects."""

import base64
import email
from email import policy

import pytest
from agentarea_common.request_transform import (
    RequestTransformError,
    apply_request_transform,
    validate_request_transform,
)

RFC822 = [{"build": "rfc822", "into": "raw"}]


def _message(body: dict) -> email.message.EmailMessage:
    raw = base64.urlsafe_b64decode(body["raw"])
    return email.message_from_bytes(raw, policy=policy.default)


def test_mail_fields_become_one_encoded_message():
    body = apply_request_transform(
        RFC822,
        {
            "from": "Артём <artem@agentarea.ai>",
            "to": ["client@example.com", "second@example.com"],
            "cc": "boss@example.com",
            "subject": "Счёт за ноябрь",
            "text": "Добрый день, счёт во вложении.",
        },
    )

    assert set(body) == {"raw"}
    message = _message(body)
    assert message["From"] == "Артём <artem@agentarea.ai>"
    assert message["To"] == "client@example.com, second@example.com"
    assert message["Cc"] == "boss@example.com"
    assert message["Subject"] == "Счёт за ноябрь"
    assert message.get_content().strip() == "Добрый день, счёт во вложении."


def test_the_encoding_is_base64url():
    body = apply_request_transform(RFC822, {"to": "a@example.com", "text": "?" * 300})

    assert "+" not in body["raw"] and "/" not in body["raw"]


def test_text_and_html_become_alternatives():
    message = _message(
        apply_request_transform(
            RFC822, {"to": "a@example.com", "text": "plain", "html": "<p>rich</p>"}
        )
    )

    assert message.get_content_type() == "multipart/alternative"
    assert message.get_body(("plain",)).get_content().strip() == "plain"
    assert message.get_body(("html",)).get_content().strip() == "<p>rich</p>"


def test_html_alone_is_an_html_message():
    message = _message(apply_request_transform(RFC822, {"to": "a@example.com", "html": "<b>x</b>"}))

    assert message.get_content_type() == "text/html"


def test_a_reply_carries_its_thread_headers():
    message = _message(
        apply_request_transform(
            RFC822,
            {
                "to": "a@example.com",
                "text": "ok",
                "reply_to": "team@example.com",
                "in_reply_to": "<m1@example.com>",
                "references": ["<m0@example.com>", "<m1@example.com>"],
            },
        )
    )

    assert message["Reply-To"] == "team@example.com"
    assert message["In-Reply-To"] == "<m1@example.com>"
    assert message["References"] == "<m0@example.com> <m1@example.com>"


def test_fields_that_are_not_mail_pass_through():
    body = apply_request_transform(
        RFC822, {"to": "a@example.com", "text": "ok", "threadId": "18c0"}
    )

    assert body["threadId"] == "18c0"
    assert "to" not in body and "text" not in body


def test_no_steps_leave_the_body_alone():
    assert apply_request_transform([], {"to": "a@example.com"}) == {"to": "a@example.com"}


@pytest.mark.parametrize(
    "fields",
    [
        {"text": "nobody to send to"},
        {"to": "a@example.com"},
        {"to": "a@example.com", "text": "x", "subject": "line\r\nBcc: victim@example.com"},
        {"to": ["a@example.com", 3], "text": "x"},
    ],
    ids=["no-recipient", "no-content", "header-injection", "non-text-address"],
)
def test_a_message_that_cannot_be_built_is_refused(fields):
    with pytest.raises(RequestTransformError):
        apply_request_transform(RFC822, fields)


def test_a_body_that_is_not_an_object_is_refused():
    with pytest.raises(RequestTransformError):
        apply_request_transform(RFC822, "raw text")


@pytest.mark.parametrize(
    "steps",
    [
        {"build": "rfc822", "into": "raw"},
        [{"build": "mime", "into": "raw"}],
        [{"build": "rfc822"}],
        [{"build": "rfc822", "into": ""}],
        ["rfc822"],
    ],
    ids=["not-a-list", "unknown-kind", "no-into", "empty-into", "not-an-object"],
)
def test_a_malformed_declaration_is_refused(steps):
    with pytest.raises(RequestTransformError):
        validate_request_transform(steps)


def test_a_well_formed_declaration_passes():
    validate_request_transform(RFC822)
