"""Refuse NUL characters at the request boundary.

PostgreSQL ``text``, ``varchar`` and ``jsonb`` cannot hold U+0000, so a string
carrying one fails at the first query that binds it: a 500 for what is a
malformed request. Any path segment, query value or JSON string may end up in a
column, so the rule is enforced once, here, instead of on every field.
"""

import json
from typing import Any

from agentarea_common.exceptions import problem_response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_NUL = "\x00"


def contains_nul(value: Any) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if _NUL in item:
                return True
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return False


def _is_json(content_type: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


class NulCharacterMiddleware(BaseHTTPMiddleware):
    """Answer 422 for a request whose path, query or JSON body holds U+0000."""

    async def dispatch(self, request: Request, call_next):
        if _NUL in request.url.path or contains_nul(request.query_params.multi_items()):
            return _refused()
        if _is_json(request.headers.get("content-type", "")):
            body = await request.body()
            try:
                payload = json.loads(body) if body else None
            except (ValueError, RecursionError):
                # Not JSON this layer can read; request validation reports it.
                payload = None
            if contains_nul(payload):
                return _refused()
        return await call_next(request)


def _refused():
    return problem_response(
        status_code=422,
        code="nul_character",
        detail="Request contains a NUL (U+0000) character, which cannot be stored",
    )
