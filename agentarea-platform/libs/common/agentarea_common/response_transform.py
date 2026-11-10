"""Reshape a vendor's response before the agent sees it, as the connector declares.

``x-agentarea-response-transform`` on an OpenAPI operation is a list of steps, each
replacing the value at ``at`` in the decoded JSON body::

    [{"decode": "base64", "at": "$.rawData"}, {"parse": "xml", "at": "$.rawData"}]

An XML response arrives as its text, so ``{"parse": "xml", "at": "$"}`` replaces the
whole body.

A mail message Gmail returns as ``raw`` reads as its fields::

    [{"decode": "base64url", "at": "$.raw"}, {"parse": "rfc822", "at": "$.raw"}]

``base64url`` keeps bytes that are not UTF-8 as escapes, so the parse that follows
sees the message as sent, whatever its charset. ``rfc822`` gives the headers, the
plain-text body, the HTML body only when there is no plain one, and each
attachment's name, type and size, never its content.

Parsed XML becomes JSON the way ``xmltodict`` writes it: an element is an object
keyed by child tag, attributes as ``@name``, text as ``#text`` (or the bare string
when the element has nothing else), and repeated children as a list.
"""

import base64
import binascii
import re
import xml.etree.ElementTree as ET
from email import message_from_bytes
from email import policy as email_policy
from email.message import EmailMessage
from typing import Any

from .tool_cost import json_path

_MAX_XML_BYTES = 8 << 20
_BASE64URL = re.compile(r"[A-Za-z0-9_-]*={0,2}")


class ResponseTransformError(ValueError):
    """A transform is malformed, or the response does not fit it."""


def _element(node: ET.Element) -> Any:
    out: dict[str, Any] = {f"@{name}": value for name, value in node.attrib.items()}
    for child in node:
        value = _element(child)
        if child.tag in out:
            existing = out[child.tag]
            out[child.tag] = [*existing, value] if isinstance(existing, list) else [existing, value]
        else:
            out[child.tag] = value
    text = (node.text or "").strip()
    if not out:
        return text
    if text:
        out["#text"] = text
    return out


def _parse_xml(value: Any) -> Any:
    raw = value.encode() if isinstance(value, str) else value
    if not isinstance(raw, bytes):
        raise ResponseTransformError("xml input must be text")
    if len(raw) > _MAX_XML_BYTES:
        raise ResponseTransformError("xml document is too large")
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ResponseTransformError("xml documents with a DOCTYPE or ENTITY are refused")
    try:
        root = ET.fromstring(raw)  # noqa: S314 - no DOCTYPE, no entities, bounded size
    except ET.ParseError as error:
        raise ResponseTransformError(f"invalid xml: {error}") from error
    return {root.tag: _element(root)}


def _decode_base64(value: Any) -> str:
    if not isinstance(value, str):
        raise ResponseTransformError("base64 input must be text")
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ResponseTransformError(f"invalid base64: {error}") from error


def _decode_base64url(value: Any) -> str:
    if not isinstance(value, str):
        raise ResponseTransformError("base64url input must be text")
    if not _BASE64URL.fullmatch(value):
        raise ResponseTransformError("invalid base64url: unexpected characters")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as error:
        raise ResponseTransformError(f"invalid base64url: {error}") from error
    return raw.decode("utf-8", errors="surrogateescape")


_RFC822_HEADERS = {
    "from": "From",
    "to": "To",
    "cc": "Cc",
    "reply_to": "Reply-To",
    "subject": "Subject",
    "date": "Date",
    "message_id": "Message-ID",
    "in_reply_to": "In-Reply-To",
    "references": "References",
}


def _part_text(part: Any) -> str:
    try:
        return part.get_content()
    except LookupError, UnicodeDecodeError:
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def _parse_rfc822(value: Any) -> dict[str, Any]:
    raw = value.encode("utf-8", errors="surrogateescape") if isinstance(value, str) else value
    if not isinstance(raw, bytes):
        raise ResponseTransformError("rfc822 input must be text")
    message = message_from_bytes(raw, policy=email_policy.default)
    if not isinstance(message, EmailMessage):
        raise ResponseTransformError("rfc822 input is not a message")

    out: dict[str, Any] = {
        field: str(message[header])
        for field, header in _RFC822_HEADERS.items()
        if message[header] is not None
    }
    plain = message.get_body(preferencelist=("plain",))
    out["text"] = _part_text(plain) if plain is not None else ""
    if plain is None:
        html = message.get_body(preferencelist=("html",))
        if html is not None:
            out["html"] = _part_text(html)
    out["attachments"] = [
        {
            "filename": part.get_filename(),
            "content_type": part.get_content_type(),
            "size": len(part.get_payload(decode=True) or b""),
        }
        for part in message.iter_attachments()
    ]
    return out


_STEPS = {
    ("decode", "base64"): _decode_base64,
    ("decode", "base64url"): _decode_base64url,
    ("parse", "xml"): _parse_xml,
    ("parse", "rfc822"): _parse_rfc822,
}


def _set(doc: Any, path: str, value: Any) -> None:
    parent_path, _, key = path.rpartition(".")
    if not parent_path or "[" in key:
        raise ResponseTransformError(f"cannot replace {path}: it must end in .field")
    parent = json_path(doc, parent_path)
    parent[key] = value


def apply_response_transform(steps: list[dict[str, Any]], body: Any) -> Any:
    """The body with every step applied in order; any failure raises."""
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("at"), str):
            raise ResponseTransformError(f"a transform step needs at: <path>, got {step!r}")
        kinds = [(kind, step[kind]) for kind in ("decode", "parse") if kind in step]
        if len(kinds) != 1 or kinds[0] not in _STEPS:
            raise ResponseTransformError(f"unknown transform step {step!r}")
        path = step["at"]
        try:
            current = json_path(body, path)
        except KeyError:
            raise ResponseTransformError(f"the response carries no {path}") from None
        value = _STEPS[kinds[0]](current)
        if path == "$":
            body = value
        else:
            _set(body, path, value)
    return body
