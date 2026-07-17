"""Register the unified exception handlers with a FastAPI app."""

from fastapi import FastAPI

from .handlers import ERROR_HANDLERS


def register_error_handlers(app: FastAPI) -> None:
    """Register all unified error handlers (problem+json) with the app.

    Covers AppError (incl. workspace errors), PermissionError, request
    validation, HTTPException, DB integrity violations, and a catch-all so no
    response is ever a non-JSON body.
    """
    for exception_class, handler in ERROR_HANDLERS.items():
        app.add_exception_handler(exception_class, handler)


def register_single_error_handler(app: FastAPI, exception_class: type, handler) -> None:
    """Register a single error handler."""
    app.add_exception_handler(exception_class, handler)


# Backwards-compatible aliases (former workspace-only names).
register_workspace_error_handlers = register_error_handlers
register_single_workspace_error_handler = register_single_error_handler
