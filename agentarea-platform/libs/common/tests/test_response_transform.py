"""A connector can declare how a vendor's response is reshaped before the agent sees it."""

import base64

import pytest
from agentarea_common.response_transform import ResponseTransformError, apply_response_transform

XML = (
    '<?xml version="1.0" encoding="utf-8"?><yandexsearch version="1.0"><response>'
    '<results><grouping><group><doc id="a"><url>https://a.example</url><title>A</title></doc>'
    '</group><group><doc id="b"><url>https://b.example</url><title>B <hlword>b</hlword></title>'
    "</doc></group></grouping></results></response></yandexsearch>"
)

STEPS = [{"decode": "base64", "at": "$.rawData"}, {"parse": "xml", "at": "$.rawData"}]


def _body(xml: str) -> dict:
    return {"rawData": base64.b64encode(xml.encode()).decode()}


def test_base64_xml_becomes_json():
    body = apply_response_transform(STEPS, _body(XML))

    groups = body["rawData"]["yandexsearch"]["response"]["results"]["grouping"]["group"]
    assert [g["doc"]["@id"] for g in groups] == ["a", "b"]
    assert groups[0]["doc"]["url"] == "https://a.example"
    assert groups[1]["doc"]["title"] == {"#text": "B", "hlword": "b"}
    assert body["rawData"]["yandexsearch"]["@version"] == "1.0"


def test_an_xml_body_is_parsed_at_the_root():
    body = apply_response_transform(
        [{"parse": "xml", "at": "$"}], '<serp><item pos="1">a</item><item pos="2">b</item></serp>'
    )

    assert body == {"serp": {"item": [{"@pos": "1", "#text": "a"}, {"@pos": "2", "#text": "b"}]}}


def test_no_steps_leave_the_body_alone():
    body = {"a": 1}
    assert apply_response_transform([], body) is body


def test_a_document_with_a_doctype_is_refused():
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'

    with pytest.raises(ResponseTransformError, match="DOCTYPE"):
        apply_response_transform(STEPS, _body(evil))


def test_a_missing_field_is_an_error():
    with pytest.raises(ResponseTransformError, match=r"\$\.rawData"):
        apply_response_transform(STEPS, {"other": 1})


@pytest.mark.parametrize(
    "steps",
    [[{"decode": "rot13", "at": "$.x"}], [{"parse": "yaml", "at": "$.x"}], [{"at": "$.x"}]],
)
def test_an_unknown_step_is_refused(steps):
    with pytest.raises(ResponseTransformError):
        apply_response_transform(steps, {"x": "eA=="})


GMAIL_RAW_STEPS = [{"decode": "base64url", "at": "$.raw"}, {"parse": "rfc822", "at": "$.raw"}]


def _gmail_raw(message: bytes) -> dict:
    return {"id": "m1", "raw": base64.urlsafe_b64encode(message).decode().rstrip("=")}


def test_a_raw_message_becomes_its_fields_and_text():
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "Артём <artem@agentarea.ai>"
    message["To"] = "a@example.com, b@example.com"
    message["Subject"] = "Счёт за ноябрь"
    message["Message-ID"] = "<m1@example.com>"
    message.set_content("Добрый день")
    message.add_alternative("<p>Добрый день</p>", subtype="html")
    message.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="invoice.pdf")

    body = apply_response_transform(GMAIL_RAW_STEPS, _gmail_raw(message.as_bytes()))

    mail = body["raw"]
    assert body["id"] == "m1"
    assert mail["from"] == "Артём <artem@agentarea.ai>"
    assert mail["to"] == "a@example.com, b@example.com"
    assert mail["subject"] == "Счёт за ноябрь"
    assert mail["message_id"] == "<m1@example.com>"
    assert mail["text"].strip() == "Добрый день"
    assert "html" not in mail
    assert mail["attachments"] == [
        {"filename": "invoice.pdf", "content_type": "application/pdf", "size": 4}
    ]


def test_an_html_only_message_keeps_its_html():
    raw = (
        b"From: a@example.com\r\nTo: b@example.com\r\nSubject: hi\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n<b>hi</b>\r\n"
    )

    mail = apply_response_transform(GMAIL_RAW_STEPS, _gmail_raw(raw))["raw"]

    assert mail["html"].strip() == "<b>hi</b>"
    assert mail["text"] == ""


def test_a_message_in_a_legacy_charset_is_read():
    raw = (
        b"From: a@example.com\r\nSubject: =?windows-1251?b?0vXl8fI=?=\r\n"
        b"Content-Type: text/plain; charset=windows-1251\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n" + "Привет".encode("cp1251") + b"\r\n"
    )

    mail = apply_response_transform(GMAIL_RAW_STEPS, _gmail_raw(raw))["raw"]

    assert mail["subject"] == "Тхест"
    assert mail["text"].strip() == "Привет"


def test_invalid_base64url_is_an_error():
    with pytest.raises(ResponseTransformError, match="invalid base64url"):
        apply_response_transform(GMAIL_RAW_STEPS, {"raw": "@@@"})
