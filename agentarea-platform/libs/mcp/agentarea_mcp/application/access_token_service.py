"""Service for managing Personal Access Tokens (PATs) for MCP Bearer auth."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from agentarea_mcp.domain.auth_models import APIKey
from agentarea_mcp.infrastructure.auth_repository import APIKeyRepository

logger = logging.getLogger(__name__)

# Token prefix to identify AgentArea tokens
_TOKEN_PREFIX = "aat_"  # noqa: S105
# Number of random bytes for the token body (43 URL-safe base64 chars)
_TOKEN_BYTES = 32


def _generate_raw_token() -> str:
    """Generate a new raw token string (never stored)."""
    return _TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest of a raw token."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class APIKeyService:
    """Manage PAT lifecycle: creation, validation, revocation."""

    def __init__(self, repo: APIKeyRepository) -> None:
        self._repo = repo

    async def create_token(
        self,
        name: str,
        expires_in_days: int | None = None,
    ) -> tuple[APIKey, str]:
        """Create a new PAT.

        Returns ``(token_record, raw_token)``.  The raw token is shown once
        to the user and MUST NOT be stored — only the hash is persisted.
        """
        raw_token = _generate_raw_token()
        token_hash = hash_token(raw_token)
        token_prefix = raw_token[:12]

        expires_at: datetime | None = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        created = await self._repo.create(
            name=name,
            token_hash=token_hash,
            token_prefix=token_prefix,
            expires_at=expires_at,
        )
        logger.info("Created MCP access token '%s' (id=%s)", name, created.id)
        return created, raw_token

    async def validate_token(self, raw_token: str) -> APIKey | None:
        """Return the token record if the raw token is valid, or None.

        A token is invalid if:
        - Not found in the database
        - ``is_active`` is False (revoked)
        - ``expires_at`` is in the past
        """
        token_hash = hash_token(raw_token)
        record = await self._repo.get_by_hash(token_hash)
        if record is None:
            return None
        if not record.is_active:
            return None
        if record.is_expired():
            return None
        return record

    async def get_token(self, token_id: UUID) -> APIKey | None:
        return await self._repo.get_by_id(token_id)

    async def list_tokens(self) -> list[APIKey]:
        return await self._repo.list_all()

    async def revoke_token(self, token_id: UUID) -> bool:
        """Immediately deactivate a PAT. Returns False if not found."""
        record = await self._repo.get_by_id(token_id)
        if record is None:
            return False
        await self._repo.update(token_id, is_active=False)
        logger.info("Revoked MCP access token %s", token_id)
        return True

    async def record_access(self, token_id: UUID) -> None:
        """Increment usage counter and update last_accessed_at."""
        await self._repo.increment_access_count(token_id)
