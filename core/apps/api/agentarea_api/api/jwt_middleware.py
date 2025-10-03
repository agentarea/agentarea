"""JWT Middleware for FastAPI.

This module provides JWT authentication middleware for the FastAPI application.
It validates JWT tokens from OIDC providers and extracts user information for authenticated requests.
"""

import logging
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)


class JWTMiddleware(BaseHTTPMiddleware):
    """JWT Authentication Middleware for FastAPI."""

    def __init__(self, app, jwks_uri: str | None = None, algorithms: list[str] | None = None):
        """Initialize JWT middleware.

        Args:
            app: FastAPI application instance
            jwks_uri: URI to fetch JWKS for token verification (for OIDC)
            algorithms: List of algorithms for JWT token verification
        """
        super().__init__(app)
        self.jwks_uri = jwks_uri
        self.algorithms = algorithms or ["RS256"]
        self.jwks_cache = None

    async def dispatch(self, request: Request, call_next):
        """Process incoming requests and validate JWT tokens.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware or endpoint handler

        Returns:
            Response from the next middleware or endpoint
        """
        # Skip authentication for public routes
        if self._is_public_route(request):
            return await call_next(request)

        # Extract authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            # For non-public routes, require authentication
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authorization header missing"},
            )

        # Parse bearer token
        try:
            if not auth_header.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authorization header format",
                )

            token = auth_header[7:]  # Remove "Bearer " prefix

            # Decode and verify JWT token
            payload = await self._verify_token(token)

            # Add user information to request state
            request.state.user = payload
            request.state.user_id = payload.get("sub")

        except jwt.ExpiredSignatureError:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Token has expired"}
            )
        except jwt.InvalidTokenError as e:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": f"Invalid token: {e!s}"},
            )
        except Exception as e:
            logger.error(f"Unexpected error during JWT validation: {e}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error"},
            )

        # Continue with the request
        response = await call_next(request)
        return response

    async def _verify_token(self, token: str) -> dict[str, Any]:
        """Verify JWT token using JWKS from OIDC provider.

        Args:
            token: JWT token to verify

        Returns:
            Decoded token payload

        Raises:
            jwt.InvalidTokenError: If token verification fails
        """
        # If JWKS URI is provided, use it to verify the token
        if self.jwks_uri:
            # Fetch JWKS if not cached or cache is empty
            if not self.jwks_cache:
                async with httpx.AsyncClient() as client:
                    response = await client.get(self.jwks_uri)
                    if response.status_code == 200:
                        self.jwks_cache = response.json()
                    else:
                        raise jwt.InvalidTokenError(f"Failed to fetch JWKS: {response.status_code}")

            # Get the key ID from the token header
            header = jwt.get_unverified_header(token)
            key_id = header.get("kid")

            if not key_id:
                raise jwt.InvalidTokenError("Token header missing key ID")

            # Find the key in JWKS
            key = None
            for jwk in self.jwks_cache.get("keys", []):
                if jwk.get("kid") == key_id:
                    key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
                    break

            if not key:
                raise jwt.InvalidTokenError("Key not found in JWKS")

            # Verify the token
            return jwt.decode(token, key, algorithms=self.algorithms, options={"verify_aud": False})
        else:
            # If no JWKS URI, raise an error as we need it for OIDC
            raise jwt.InvalidTokenError("JWKS URI not configured for OIDC token verification")

    def _is_public_route(self, request: Request) -> bool:
        """Check if the request is for a public route.

        Args:
            request: Incoming HTTP request

        Returns:
            True if the route is public, False otherwise
        """
        # Define public routes that don't require authentication
        public_routes = [
            "/",
            "/health",
            "/v1/auth/login",
            "/v1/auth/register",
            "/v1/auth/token",
            "/docs",
            "/redoc",
            "/openapi.json",
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
