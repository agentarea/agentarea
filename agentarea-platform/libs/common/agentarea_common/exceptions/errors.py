"""Unified application error model and RFC 9457 (problem+json) rendering.

Every error the API returns is shaped as an RFC 9457 *problem detail* document
(``application/problem+json``) so clients always receive machine-readable JSON —
never a plain-text ``Internal Server Error``. Domain/web code raises
:class:`AppError` (or a semantic subclass); a single handler renders it. Code
that needs to emit a problem without an exception (e.g. mapping a third-party
domain exception at the composition layer) uses :func:`problem_response`.

Layering note: this is a *web-boundary* concern. Pure domain exceptions (e.g.
``BudgetCapExceededError`` in ``agentarea_tasks``) deliberately do NOT inherit
from :class:`AppError`; the API layer maps them via :func:`problem_response`.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"


def problem_dict(
    *,
    status_code: int,
    code: str,
    detail: str,
    title: str | None = None,
    type_: str = "about:blank",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an RFC 9457 problem-detail body.

    ``title`` defaults to the HTTP status phrase. ``extra`` keys are merged at the
    top level as problem extensions (RFC 9457 §3.2) and never overwrite the
    standard members.
    """
    if title is None:
        try:
            title = HTTPStatus(status_code).phrase
        except ValueError:
            title = "Error"
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status_code,
        "code": code,
        "detail": detail,
    }
    if extra:
        for key, value in extra.items():
            body.setdefault(key, value)
    return body


def problem_response(
    *,
    status_code: int,
    code: str,
    detail: str,
    title: str | None = None,
    type_: str = "about:blank",
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Render a problem-detail :class:`JSONResponse` with the problem+json type."""
    return JSONResponse(
        status_code=status_code,
        content=problem_dict(
            status_code=status_code,
            code=code,
            detail=detail,
            title=title,
            type_=type_,
            extra=extra,
        ),
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=headers,
    )


class AppError(Exception):
    """Base class for application errors rendered as RFC 9457 problem+json.

    Subclasses set the class-level ``status_code`` / ``code`` / ``title`` to
    express their HTTP semantics declaratively; a single handler renders any
    instance. ``detail`` is the human-readable, client-safe message — do not put
    internal/sensitive context here (use ``extra`` for structured public fields,
    and log the rest).
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    title: str | None = None  # defaults to the HTTP status phrase when None

    def __init__(
        self,
        detail: str | None = None,
        *,
        status_code: int | None = None,
        code: str | None = None,
        title: str | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        if title is not None:
            self.title = title
        # Fall back to the HTTP status phrase so detail is never empty.
        self.detail = detail or self.title or HTTPStatus(self.status_code).phrase
        self.extra = extra or {}
        self.headers = headers or {}
        super().__init__(self.detail)

    def to_problem(self) -> dict[str, Any]:
        """Render this error as an RFC 9457 problem-detail body."""
        return problem_dict(
            status_code=self.status_code,
            code=self.code,
            detail=self.detail,
            title=self.title,
            extra=self.extra,
        )


# --- Semantic HTTP subclasses (reuse these instead of bare HTTPException) ------


class BadRequestError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "authentication_failed"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
