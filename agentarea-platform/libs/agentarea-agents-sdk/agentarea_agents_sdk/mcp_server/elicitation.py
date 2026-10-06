"""Ask the calling MCP client to send its user to a URL, when it said it can.

URL-mode elicitation lets a server send the user to a page the model never
sees. The platform mounts are stateless, so no server-to-client request can be
sent mid-call; the ask rides the tool call's own response instead: an
``InputRequiredResult`` from protocol 2026-07-28 on, the -32042 error before
it. Either goes only to a client whose capabilities, as this request carries
them, include ``elicitation.url``. A handshake-era client on a stateless mount
declares capabilities on ``initialize`` alone, which no later tool call sees,
so it is never asked this way.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from mcp.server.mcpserver import Context
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import ElicitRequest, ElicitRequestURLParams, InputRequiredResult
from mcp.types.version import is_version_at_least

_INPUT_REQUIRED_VERSION = "2026-07-28"
_ELICITATION_KEY = "connect"

_call_context_var: ContextVar[Context[Any, Any] | None] = ContextVar(
    "mcp_call_context", default=None
)


@contextmanager
def mcp_call_context(context: Context[Any, Any]) -> Iterator[None]:
    """Expose the MCP request *context* to the tool call run inside."""
    token = _call_context_var.set(context)
    try:
        yield
    finally:
        _call_context_var.reset(token)


def url_elicitation(url: str, message: str) -> InputRequiredResult | None:
    """What a tool returns to ask the caller's user to open *url*.

    ``None`` when the call cannot carry the ask: outside an MCP call, for a
    client that did not declare URL elicitation on this request, or on the
    retry after the client already answered it. A handshake-era client that
    did declare it gets the -32042 error, the only form its protocol has, so
    this raises ``UrlElicitationRequiredError`` there.
    """
    context = _call_context_var.get()
    if context is None or context.protocol_version is None:
        return None
    if context.input_responses or context.request_state is not None:
        return None
    capabilities = context.client_capabilities
    if capabilities is None or capabilities.elicitation is None:
        return None
    if capabilities.elicitation.url is None:
        return None
    if is_version_at_least(context.protocol_version, _INPUT_REQUIRED_VERSION):
        return InputRequiredResult(
            input_requests={
                _ELICITATION_KEY: ElicitRequest(
                    params=ElicitRequestURLParams(message=message, url=url)
                )
            }
        )
    raise UrlElicitationRequiredError(
        [ElicitRequestURLParams(message=message, url=url, elicitation_id=uuid4().hex)],
        message=message,
    )
