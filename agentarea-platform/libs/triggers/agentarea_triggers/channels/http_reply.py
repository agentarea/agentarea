"""The one generic reply sender: a reply that is one HTTP request (ADR-0040 §5).

The catalog entry's ``reply`` block describes the request — URL, headers and
JSON body as templates over ``{credentials.k}``, ``{target:k}`` and
``{message}`` — the markup flavour and the length limit. Nothing here names a
provider: adding one is a catalog entry.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from agentarea_common.outbound import Destination, outbound_client
from agentarea_streams.domain.templates import TemplateContext, TemplateError, render, render_value

from .exceptions import FatalError, RetryableError
from .markup import format_event, limited, markup
from .source_credentials import CredentialReader, credentials_of

if TYPE_CHECKING:
    from agentarea_streams.domain.source_types import Reply

logger = logging.getLogger(__name__)

#: The key of the delivery config that carries the catalog entry's reply block.
REPLY_KEY = "reply"


def reply_of(config: dict[str, Any]) -> Reply:
    reply = config.get(REPLY_KEY)
    if reply is None:
        raise FatalError(f"no reply block for {config.get('type')!r}")
    return reply


class HttpReplyAdapter:
    """Formats in the entry's markup and sends the entry's request."""

    def __init__(self, credentials: CredentialReader) -> None:
        self._credentials = credentials

    def format(self, event: dict[str, Any], presentation: str, config: dict[str, Any]) -> str:
        return format_event(markup(reply_of(config).markup), event, presentation)

    async def send(self, config: dict[str, Any], message: str) -> None:
        if not message:
            return
        reply = reply_of(config)
        request = reply.request
        if request is None:
            raise FatalError(f"the {config.get('type')!r} reply block has no request")
        credential_type, credential_key = credentials_of(config)
        credentials = await self._credentials(
            workspace_id=str(config["workspace_id"]),
            owner=str(config["owner"]),
            credential_type=credential_type,
            credential_key=credential_key,
        )
        context = TemplateContext(
            values={
                "credentials": credentials,
                "target": config.get("target") or {},
                "message": limited(markup(reply.markup), message, reply.limit),
            }
        )
        try:
            url = render(request.url, context)
            headers = render_value(request.headers, context) or {}
            body = (
                render_value(request.json_body, context) if request.json_body is not None else None
            )
        except TemplateError as error:
            raise FatalError(
                f"the {config.get('type')!r} reply request is malformed: {error}"
            ) from error
        if url is None:
            raise FatalError(f"the {config.get('type')!r} reply URL cannot be filled for this task")
        missing = sorted(set(request.headers) - set(headers))
        if missing:
            raise FatalError(
                f"the {config.get('type')!r} reply headers {', '.join(missing)} cannot be filled"
            )
        try:
            async with outbound_client(Destination.VENDOR, timeout=10.0) as client:
                response = await client.request(request.method, url, json=body, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise RetryableError(f"network: {error}") from error
        except httpx.HTTPError as error:
            raise RetryableError(f"http error: {error}") from error
        raise_for_reply(response, reply.permanent_errors)


def _refused(response: httpx.Response) -> bool:
    """A 2xx answer whose JSON says ``"ok": false`` is a refusal, not a delivery."""
    if not response.is_success:
        return True
    if "json" not in response.headers.get("content-type", ""):
        return False
    try:
        answer = response.json()
    except ValueError:
        return False
    return isinstance(answer, dict) and answer.get("ok") is False


def raise_for_reply(response: httpx.Response, permanent_errors: list[str]) -> None:
    """Nothing for a delivered reply; otherwise a retryable or a permanent failure.

    An answer naming one of the entry's ``permanent_errors`` is permanent; past
    that, 429 and 5xx are retried, any other 4xx is permanent, and a 2xx refusal
    is retried until the attempts run out.
    """
    if not _refused(response):
        return
    status = response.status_code
    text = response.text[:300] if response.text else ""
    if any(marker in text for marker in permanent_errors):
        raise FatalError(f"refused {status}: {text}")
    if status == 429:
        retry_after = response.headers.get("Retry-After")
        try:
            hint = float(retry_after) if retry_after else None
        except ValueError:
            hint = None
        raise RetryableError(f"rate limited: {text}", retry_after=hint)
    if status >= 500 or response.is_success:
        raise RetryableError(f"refused {status}: {text}")
    raise FatalError(f"refused {status}: {text}")
