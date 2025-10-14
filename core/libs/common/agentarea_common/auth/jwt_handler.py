"""JWT token handler for user and workspace context extraction."""

import logging
import os

import jwt
from fastapi import Request

from ..config.settings import get_settings
from ..exceptions.workspace import InvalidJWTToken, MissingWorkspaceContext
from .context import UserContext

logger = logging.getLogger(__name__)


class JWTTokenHandler:
    """Handles JWT token extraction and validation."""

    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        """Initialize JWT token handler.

        Args:
            secret_key: Secret key for JWT validation
            algorithm: JWT algorithm to use
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.logger = logging.getLogger(__name__)

    async def extract_user_context(self, request: Request) -> UserContext:
        """Extract user context from JWT token in request.

        Args:
            request: FastAPI request object

        Returns:
            UserContext: Extracted user and workspace context

        Raises:
            HTTPException: If token is missing, invalid, or lacks required claims
        """
        # Extract JWT token from request
        token = self._extract_token_from_header(request)
        if not token:
            self.logger.warning("Missing authorization token in request")
            raise InvalidJWTToken(reason="Missing authorization token", token_present=False)

        try:
            # Decode JWT token with optional audience validation
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"verify_aud": False},  # Disable audience verification for now
            )

            # Extract required claims
            user_id = payload.get("sub")
            workspace_id = payload.get("workspace_id")

            if not user_id:
                self.logger.error("JWT token missing 'sub' claim")
                raise MissingWorkspaceContext(missing_field="user_id (sub claim)")

            if not workspace_id:
                self.logger.error("JWT token missing 'workspace_id' claim")
                raise MissingWorkspaceContext(missing_field="workspace_id", user_id=user_id)

            return UserContext(
                user_id=user_id, workspace_id=workspace_id, roles=payload.get("roles", [])
            )

        except jwt.InvalidTokenError as e:
            self.logger.error(f"JWT validation failed: {e}")
            raise InvalidJWTToken(reason=f"Token validation failed: {e!s}", token_present=True)

    def _extract_token_from_header(self, request: Request) -> str | None:
        """Extract Bearer token from Authorization header.

        Args:
            request: FastAPI request object

        Returns:
            Optional[str]: JWT token if found, None otherwise
        """
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]  # Remove "Bearer " prefix
        return None


def get_jwt_handler() -> JWTTokenHandler:
    """Get JWT token handler with application settings.

    Returns:
        JWTTokenHandler: Configured JWT handler
    """
    settings = get_settings()
    return JWTTokenHandler(
        secret_key=settings.app.JWT_SECRET_KEY, algorithm=settings.app.JWT_ALGORITHM
    )
