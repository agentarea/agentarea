"""Authentication module for AgentArea.

This module provides a modular authentication system that can be easily extended
to support different authentication providers.
"""

from .authorization import AuthorizationService
from .context import UserContext
from .context_manager import ContextManager
from .dependencies import UserContextDep, get_user_context
from .jwt_handler import JWTTokenHandler, get_jwt_handler
from .permission import PermissionService, require_permission
from .simple_permission import SimplePermissionService
from .workspace_authorization import WorkspaceScopedAuthorizationService

__all__ = [
    "AuthorizationService",
    "ContextManager",
    "JWTTokenHandler",
    "PermissionService",
    "SimplePermissionService",
    "UserContext",
    "UserContextDep",
    "WorkspaceScopedAuthorizationService",
    "get_jwt_handler",
    "get_user_context",
    "require_permission",
]
