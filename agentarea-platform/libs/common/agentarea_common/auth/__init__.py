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
from .workspace_authorization import WorkspaceScopedAuthorizationService
from .workspace_permission import WorkspaceScopedPermissionService

__all__ = [
    "AuthorizationService",
    "ContextManager",
    "JWTTokenHandler",
    "PermissionService",
    "UserContext",
    "UserContextDep",
    "WorkspaceScopedAuthorizationService",
    "WorkspaceScopedPermissionService",
    "get_jwt_handler",
    "get_user_context",
    "require_permission",
]
