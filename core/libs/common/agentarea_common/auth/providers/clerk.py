"""
Clerk authentication provider for AgentArea.

This module provides implementation for Clerk authentication verification
using JWT tokens.
"""

import logging
from typing import Dict, Any, Optional
import jwt
import time

from .base import BaseAuthProvider
from ..interfaces import AuthResult, AuthToken

logger = logging.getLogger(__name__)


class ClerkAuthProvider(BaseAuthProvider):
    """Clerk authentication provider implementation."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the Clerk auth provider.
        
        Args:
            config: Configuration dictionary for the provider
                   Should include:
                   - jwks_url: URL to fetch JWKS from
                   - issuer: Expected issuer URL
                   - audience: Expected audience (optional)
        """
        super().__init__(config)
        self.jwks_url = self.config.get("jwks_url")
        self.issuer = self.config.get("issuer")
        self.audience = self.config.get("audience")
        
        if not self.jwks_url:
            raise ValueError("jwks_url is required for ClerkAuthProvider")
            
        if not self.issuer:
            raise ValueError("issuer is required for ClerkAuthProvider")

    async def verify_token(self, token: str) -> AuthResult:
        """
        Verify a Clerk JWT token.
        
        Args:
            token: The JWT token to verify
            
        Returns:
            AuthResult containing the verification result
        """
        try:
            # Decode the token header to get the key ID
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            
            if not kid:
                return AuthResult(
                    is_authenticated=False,
                    error="Token header missing key ID"
                )
            
            # Fetch JWKS
            jwks = await self._fetch_jwks(self.jwks_url)
            
            # Find the key by key ID
            key = self._find_key_by_kid(jwks, kid)
            if not key:
                return AuthResult(
                    is_authenticated=False,
                    error="Key not found in JWKS"
                )
            
            # Convert JWK to RSA key
            rsa_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
            
            # Verify and decode the token
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer
            )
            
            # Validate claims
            if not self._validate_claims(payload, self.issuer):
                return AuthResult(
                    is_authenticated=False,
                    error="Invalid token claims"
                )
            
            # Extract user information
            user_id = payload.get("sub")
            if not user_id:
                return AuthResult(
                    is_authenticated=False,
                    error="Token missing user ID"
                )
            
            email = payload.get("email")
            
            auth_token = AuthToken(
                user_id=user_id,
                email=email,
                claims=payload,
                expires_at=payload.get("exp")
            )
            
            return AuthResult(
                is_authenticated=True,
                user_id=user_id,
                token=auth_token
            )
            
        except jwt.ExpiredSignatureError:
            return AuthResult(
                is_authenticated=False,
                error="Token has expired"
            )
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid token: {e}")
            return AuthResult(
                is_authenticated=False,
                error=f"Invalid token: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error verifying token: {e}")
            return AuthResult(
                is_authenticated=False,
                error=f"Error verifying token: {str(e)}"
            )

    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user information by user ID.
        
        For Clerk, we don't fetch user info directly in this implementation
        as the token already contains the necessary information.
        In a full implementation, this would call the Clerk API.
        
        Args:
            user_id: The user ID to look up
            
        Returns:
            Dictionary containing user information or None if not found
        """
        # In a real implementation, this would call the Clerk API
        # For now, we return minimal user info
        return {
            "user_id": user_id,
            "provider": "clerk"
        }

    def get_provider_name(self) -> str:
        """
        Get the name of this authentication provider.
        
        Returns:
            The provider name
        """
        return "clerk"
