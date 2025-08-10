"""Authentication module for AgentArea.

This module provides a modular authentication system that can be easily extended
to support different authentication providers.
"""

from .context import UserContext
from .context_manager import ContextManager
from .dependencies import UserContextDep, get_user_context
from .jwt_handler import JWTTokenHandler, get_jwt_handler

__all__ = [
    "ContextManager",
    "JWTTokenHandler",
    "UserContext",
    "UserContextDep",
    "get_jwt_handler",
    "get_user_context",
]
