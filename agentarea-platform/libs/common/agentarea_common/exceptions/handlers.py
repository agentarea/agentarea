"""Unified exception handlers rendering RFC 9457 problem+json.

A small fixed set of handlers covers every error path so the API never returns a
non-JSON body:

* :class:`AppError` (incl. all workspace errors) -> its declared status + shape
* builtin ``PermissionError`` -> 403
* ``RequestValidationError`` -> 422 (with the field errors as an extension)
* Starlette ``HTTPException`` -> problem+json (preserves headers like
  ``WWW-Authenticate``)
* SQLAlchemy ``IntegrityError`` -> 409 for unique/FK violations, else 500
* any other ``Exception`` -> 500 (logged with traceback, generic detail)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..auth.context_manager import ContextManager
from ..auth.dependencies import _www_authenticate_bearer
from .errors import PROBLEM_JSON_MEDIA_TYPE, AppError, problem_dict, problem_response
from .workspace import WorkspaceError

logger = logging.getLogger(__name__)

# PostgreSQL SQLSTATE codes mapped to HTTP 409 Conflict. Other integrity errors
# (e.g. 23502 not-null, which signals a bug) fall through to a 500.
_CONFLICT_SQLSTATES = {"23505", "23503"}  # unique_violation, foreign_key_violation


def _get_workspace_context_for_logging() -> dict[str, Any]:
    """Get current workspace context for logging (empty if unavailable)."""
    try:
        context = ContextManager.get_context()
        if context:
            return {"workspace_id": context.workspace_id, "user_id": context.user_id}
    except Exception:  # noqa: S110
        pass
    return {}


def _get_workspace_headers() -> dict[str, str]:
    """Get workspace context headers (``X-Workspace-ID``) for API responses."""
    headers: dict[str, str] = {}
    try:
        context = ContextManager.get_context()
        if context and context.workspace_id:
            headers["X-Workspace-ID"] = context.workspace_id
    except Exception:  # noqa: S110
        pass
    return headers


def _log_level_for(status_code: int) -> int:
    """Pick a log level: 5xx -> ERROR, auth/not-found -> INFO, else WARNING."""
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return logging.ERROR
    if status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ):
        return logging.INFO
    return logging.WARNING


def _log_error(exc: Exception, request: Request, status_code: int, *, with_traceback: bool) -> None:
    """Log an error with request + workspace context at a status-appropriate level."""
    log_context: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "request_method": request.method,
        "request_path": request.url.path,
        **_get_workspace_context_for_logging(),
    }
    # Surface structured context attached by domain exceptions.
    for attr in ("resource_type", "resource_id", "missing_field", "reason"):
        if hasattr(exc, attr):
            log_context[attr] = getattr(exc, attr)

    logger.log(
        _log_level_for(status_code),
        "Request failed: %s",
        type(exc).__name__,
        extra=log_context,
        exc_info=with_traceback,
    )


def _json_problem(
    body: dict[str, Any], status_code: int, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=headers or None,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Render any :class:`AppError` (incl. workspace errors) as problem+json."""
    # 5xx are unexpected; capture a traceback. 4xx are expected client/security
    # conditions and log at a quieter level without stack noise.
    with_traceback = exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR
    _log_error(exc, request, exc.status_code, with_traceback=with_traceback)

    headers = {**_get_workspace_headers(), **exc.headers}
    if exc.status_code == status.HTTP_401_UNAUTHORIZED and "WWW-Authenticate" not in headers:
        # An error handler must never itself raise; fall back to a bare challenge
        # if the settings-derived realm cannot be built.
        try:
            headers["WWW-Authenticate"] = _www_authenticate_bearer()
        except Exception:
            headers["WWW-Authenticate"] = "Bearer"

    return _json_problem(exc.to_problem(), exc.status_code, headers)


async def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
    """Map builtin ``PermissionError`` (write-protection layer) to 403."""
    _log_error(exc, request, status.HTTP_403_FORBIDDEN, with_traceback=False)
    body = problem_dict(
        status_code=status.HTTP_403_FORBIDDEN,
        code="permission_denied",
        detail=str(exc) or "You do not have permission to perform this action",
    )
    return _json_problem(body, status.HTTP_403_FORBIDDEN, _get_workspace_headers())


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render request validation failures as 422 problem+json with field errors."""
    _log_error(exc, request, status.HTTP_422_UNPROCESSABLE_ENTITY, with_traceback=False)
    # exc.errors() may contain non-JSON-serializable values (e.g. ValueError in
    # ctx); coerce defensively so the handler itself never 500s.
    try:
        errors = exc.errors()
    except Exception:
        errors = []
    body = problem_dict(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        detail="Request validation failed",
        extra={"errors": jsonable(errors)},
    )
    return _json_problem(body, status.HTTP_422_UNPROCESSABLE_ENTITY, _get_workspace_headers())


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Render Starlette/FastAPI ``HTTPException`` as problem+json."""
    _log_error(exc, request, exc.status_code, with_traceback=False)
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    body = problem_dict(
        status_code=exc.status_code,
        code="http_error",
        detail=detail,
    )
    headers = {**_get_workspace_headers(), **(exc.headers or {})}
    return _json_problem(body, exc.status_code, headers)


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Map DB integrity violations: unique/FK -> 409, otherwise -> 500."""
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate in _CONFLICT_SQLSTATES:
        _log_error(exc, request, status.HTTP_409_CONFLICT, with_traceback=False)
        body = problem_dict(
            status_code=status.HTTP_409_CONFLICT,
            code="conflict",
            detail="The request conflicts with the current state of the resource",
        )
        return _json_problem(body, status.HTTP_409_CONFLICT, _get_workspace_headers())

    # Unexpected integrity error (e.g. not-null) — treat as a server bug.
    _log_error(exc, request, status.HTTP_500_INTERNAL_SERVER_ERROR, with_traceback=True)
    return problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        detail="Internal Server Error",
        headers=_get_workspace_headers(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: never let an unhandled exception become a plain-text 500."""
    _log_error(exc, request, status.HTTP_500_INTERNAL_SERVER_ERROR, with_traceback=True)
    return problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        detail="Internal Server Error",
        headers=_get_workspace_headers(),
    )


def jsonable(value: Any) -> Any:
    """Best-effort coercion of arbitrary values to JSON-serializable form."""
    from fastapi.encoders import jsonable_encoder

    try:
        return jsonable_encoder(value)
    except Exception:
        return str(value)


# Registry consumed by ``register_error_handlers``. Order does not matter for
# FastAPI (it matches most-specific exception class), but keep specific entries
# above the ``Exception`` catch-all for readability.
ERROR_HANDLERS: dict[type, Any] = {
    AppError: app_error_handler,
    PermissionError: permission_error_handler,
    RequestValidationError: validation_exception_handler,
    StarletteHTTPException: http_exception_handler,
    IntegrityError: integrity_error_handler,
    Exception: unhandled_exception_handler,
}

# Backwards-compatible alias (was workspace-only). Workspace errors are now
# AppError subclasses handled by ``app_error_handler``.
WORKSPACE_ERROR_HANDLERS = ERROR_HANDLERS


def workspace_error_handler(request: Request, exc: WorkspaceError) -> Any:
    """Deprecated: WorkspaceError is an AppError; use ``app_error_handler``."""
    return app_error_handler(request, exc)
