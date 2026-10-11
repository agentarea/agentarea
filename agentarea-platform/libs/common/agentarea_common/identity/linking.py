"""Single-use codes that prove one person holds both accounts.

The person signs in to the platform and asks for a code; the platform hands it
to the messenger in a deep link; the messenger account that opens it is asked
to confirm, naming the platform account it would join. Both sides are proven:
the code is bound to the signed-in user, and only the messenger account that
redeemed it can confirm. Typing an account id proves nothing and is not offered.
"""

from __future__ import annotations

import hashlib
import secrets

import redis.asyncio as redis

#: How long a code, and a redeemed code waiting for confirmation, stays usable.
LINK_TTL_SECONDS = 600

_CODE_PREFIX = "identity:link:code"
_PENDING_PREFIX = "identity:link:pending"


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class LinkCodes:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def issue(self, user_id: str) -> str:
        """A fresh code for ``user_id``; only its digest is stored."""
        code = secrets.token_urlsafe(24)
        await self._redis().set(f"{_CODE_PREFIX}:{_digest(code)}", user_id, ex=LINK_TTL_SECONDS)
        return code

    async def redeem(self, code: str, *, provider: str, external_id: str) -> str | None:
        """Spend ``code`` from ``external_id``; returns the user awaiting its confirmation."""
        key = f"{_CODE_PREFIX}:{_digest(code)}"
        async with self._redis().pipeline(transaction=True) as pipe:
            pipe.get(key)
            pipe.delete(key)
            user_id, _ = await pipe.execute()
        if not user_id:
            return None
        await self._redis().set(
            f"{_PENDING_PREFIX}:{provider}:{external_id}", user_id, ex=LINK_TTL_SECONDS
        )
        return user_id

    async def confirm(self, *, provider: str, external_id: str) -> str | None:
        """The user ``external_id`` redeemed a code for, consumed; ``None`` if nothing waits."""
        key = f"{_PENDING_PREFIX}:{provider}:{external_id}"
        async with self._redis().pipeline(transaction=True) as pipe:
            pipe.get(key)
            pipe.delete(key)
            user_id, _ = await pipe.execute()
        return user_id or None
