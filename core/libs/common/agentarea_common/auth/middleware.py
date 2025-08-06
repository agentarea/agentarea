"""
Authentication middleware for AgentArea.

This module provides middleware for FastAPI applications to handle
authentication using the modular auth provider system.
"""

import logging
from typing import Optional
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .providers.factory import AuthProviderFactory
from .interfaces import AuthResult
from .context_manager import ContextManager
from .context import UserContext
from agentarea_common.config.app import get_app_settings

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware for FastAPI applications."""

    def __init__(self, app, provider_name: str = "clerk", config: Optional[dict] = None):
        """
        Initialize the auth middleware.
        
        Args:
            app: FastAPI application instance
            provider_name: Name of the auth provider to use
            config: Configuration for the auth provider
        """
        super().__init__(app)
        self.auth_provider = AuthProviderFactory.create_provider(provider_name, config)
        self.settings = get_app_settings()

    async def dispatch(self, request: Request, call_next):
        """
        Process incoming requests and validate authentication.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware or endpoint handler
            
        Returns:
            Response from the next middleware or endpoint
        """
        # Skip authentication for public routes
        if self._is_public_route(request):
            return await call_next(request)

        # Development mode: bypass authentication with default values
        if self.settings.DEV_MODE:
            dev_user_id = "dev-user"
            workspace_id = "default"
            
            # Set user context for development
            user_context = UserContext(
                user_id=dev_user_id,
                workspace_id=workspace_id,
                roles=["dev"]
            )
            ContextManager.set_context(user_context)
            
            try:
                response = await call_next(request)
                return response
            finally:
                # Clear context after request
                ContextManager.clear_context()

        # Production mode: require proper authentication
        # Extract authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authorization header missing"}
            )

        # Parse bearer token
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid authorization header format"}
            )

        token = auth_header[7:]  # Remove "Bearer " prefix

        # Verify token
        try:
            auth_result: AuthResult = await self.auth_provider.verify_token(token)
            
            if not auth_result.is_authenticated:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": auth_result.error or "Invalid token"}
                )
            
            # Extract workspace_id from header if not in token
            workspace_id = request.headers.get("X-Workspace-ID", "default")
            
            # Set user context
            if auth_result.token:
                user_context = UserContext(
                    user_id=auth_result.token.user_id,
                    workspace_id=workspace_id,
                    roles=[]  # In a real implementation, this would come from the token or database
                )
                ContextManager.set_context(user_context)
                
        except Exception as e:
            logger.error(f"Unexpected error during token validation: {e}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error"}
            )

        # Continue with the request
        try:
            response = await call_next(request)
            return response
        finally:
            # Clear context after request
            ContextManager.clear_context()

    def _is_public_route(self, request: Request) -> bool:
        """
        Check if the request is for a public route.
        
        Args:
            request: Incoming HTTP request
            
        Returns:
            True if the route is public, False otherwise
        """
        # Define public routes that don't require authentication
        public_routes = [
            "/",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/dev/token",  # Development endpoint
        ]
        
        # Check if the request path is in the public routes
        if request.url.path in public_routes:
            return True
            
        # Check if the request path starts with any public prefix
        public_prefixes = [
            "/static/",
            "/v1/auth/",  # All auth endpoints are public
        ]
        
        for prefix in public_prefixes:
            if request.url.path.startswith(prefix):
                return True
                
        return False
