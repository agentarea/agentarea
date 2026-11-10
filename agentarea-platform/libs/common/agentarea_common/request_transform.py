"""Shape the agent's arguments into the request a vendor expects, as the connector declares.

``x-agentarea-request-transform`` on an OpenAPI operation is a list of steps applied
in order to the JSON body before it is sent::

    [{"build": "rfc822", "into": "raw"}]

``rfc822`` takes the mail fields (``from``, ``to``, ``cc``, ``bcc``, ``reply_to``,
``subject``, ``text``, ``html``, ``in_reply_to``, ``references``) out of the body and
puts the message they make, base64url-encoded, at ``into``. Every other field passes
through, so Gmail's ``threadId`` reaches Gmail as it was given.
"""

import base64
from email.message import EmailMessage
from typing import Any

_ADDRESS_HEADERS = {"from": "From", "to": "To", "cc": "Cc", "bcc": "Bcc", "reply_to": "Reply-To"}
_MAIL_FIELDS = {*_ADDRESS_HEADERS, "subject", "text", "html", "in_reply_to", "references"}


class RequestTransformError(ValueError):
    """A transform is malformed, or the agent's arguments do not fit it."""


def _addresses(value: Any, field: str) -> str:
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise RequestTransformError(f"{field} must be an address or a list of addresses")
    return ", ".join(item.strip() for item in items if item.strip())


def _build_rfc822(fields: dict[str, Any]) -> str:
    if not any(fields.get(field) for field in ("to", "cc", "bcc")):
        raise RequestTransformError("a message needs at least one of to, cc or bcc")
    text, html = fields.get("text"), fields.get("html")
    if not text and not html:
        raise RequestTransformError("a message needs text or html")

    message = EmailMessage()
    try:
        for field, header in _ADDRESS_HEADERS.items():
            if fields.get(field):
                message[header] = _addresses(fields[field], field)
        if fields.get("subject"):
            message["Subject"] = str(fields["subject"])
        if fields.get("in_reply_to"):
            message["In-Reply-To"] = str(fields["in_reply_to"])
        if fields.get("references"):
            references = fields["references"]
            refs = references if isinstance(references, list) else [references]
            message["References"] = " ".join(str(ref) for ref in refs)
        if text:
            message.set_content(str(text))
            if html:
                message.add_alternative(str(html), subtype="html")
        else:
            message.set_content(str(html), subtype="html")
        raw = message.as_bytes()
    except (ValueError, TypeError) as error:
        raise RequestTransformError(f"the message cannot be built: {error}") from error
    return base64.urlsafe_b64encode(raw).decode("ascii")


_BUILDERS = {"rfc822": _build_rfc822}


def validate_request_transform(steps: Any) -> None:
    """Raise unless ``steps`` is a transform this module can apply."""
    if not isinstance(steps, list):
        raise RequestTransformError("x-agentarea-request-transform must be a list")
    for step in steps:
        if not isinstance(step, dict) or step.get("build") not in _BUILDERS:
            raise RequestTransformError(f"unknown request transform step {step!r}")
        if not isinstance(step.get("into"), str) or not step["into"]:
            raise RequestTransformError(
                f"a request transform step needs into: <field>, got {step!r}"
            )


def apply_request_transform(steps: list[dict[str, Any]], body: Any) -> Any:
    """The body with every step applied in order; any failure raises."""
    validate_request_transform(steps)
    for step in steps:
        if not isinstance(body, dict):
            raise RequestTransformError("the request body must be an object")
        built = _BUILDERS[step["build"]]({k: v for k, v in body.items() if k in _MAIL_FIELDS})
        body = {k: v for k, v in body.items() if k not in _MAIL_FIELDS} | {step["into"]: built}
    return body
