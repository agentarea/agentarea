"""Utility functions for registering workspace error handlers."""

from fastapi import FastAPI

from .handlers import WORKSPACE_ERROR_HANDLERS


def register_workspace_error_handlers(app: FastAPI) -> None:
    """Register all workspace error handlers with the FastAPI app.

    This function registers exception handlers for all workspace-related
    exceptions to ensure consistent error responses and logging.

    Args:
        app: FastAPI application instance
    """
    for exception_class, handler in WORKSPACE_ERROR_HANDLERS.items():
        app.add_exception_handler(exception_class, handler)


def register_single_workspace_error_handler(app: FastAPI, exception_class: type, handler) -> None:
    """Register a single workspace error handler.

    Args:
        app: FastAPI application instance
        exception_class: Exception class to handle
        handler: Handler function for the exception
    """
    app.add_exception_handler(exception_class, handler)
