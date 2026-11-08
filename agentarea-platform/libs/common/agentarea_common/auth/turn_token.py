"""The token a turn on a client's runner acts with (ADR-0051).

Issued with each turn the runner takes: ``sub`` the turn's actor (the person
who sent its message, or the agent when the run acts as the agent), ``act`` the
client, ``aud`` the task, ``jti`` the turn, signed with a key derived from the
MCP gateway secret. A signature and an expiry are not enough to end it with the
turn, so the turn is also kept live in Redis while its runner heartbeats it and
dropped when it ends; a token whose turn is not live is refused.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Literal

import jwt
import redis.asyncio as redis

logger = logging.getLogger(__name__)

TURN_TOKEN_KID = "agentarea-turn"  # noqa: S105 - a key id, not a secret
_ISSUER = "agentarea"
_DERIVATION = "agentarea/turn-token/v1"
_AUDIENCE_PREFIX = "task:"
_CLIENT_PREFIX = "client:"

ActorType = Literal["user", "agent"]


@dataclass(frozen=True)
class TurnClaims:
    """What a turn's token says: who acts, through which client, on which task."""

    turn_id: str
    task_id: str
    workspace_id: str
    client_id: str
    actor_type: ActorType
    actor_id: str
    # The person the task is attributed to; the user an agent actor acts under.
    on_behalf_of: str


def _signing_key() -> bytes:
    from ..config import get_settings

    return hmac.new(
        get_settings().mcp.gateway_secret().encode("utf-8"),
        _DERIVATION.encode("utf-8"),
        hashlib.sha256,
    ).digest()


def issue_turn_token(claims: TurnClaims, ttl_seconds: int, *, now: float | None = None) -> str:
    issued_at = int(now if now is not None else time.time())
    return jwt.encode(
        {
            "iss": _ISSUER,
            "sub": f"{claims.actor_type}:{claims.actor_id}",
            "act": {"sub": f"{_CLIENT_PREFIX}{claims.client_id}"},
            "aud": f"{_AUDIENCE_PREFIX}{claims.task_id}",
            "iat": issued_at,
            "exp": issued_at + ttl_seconds,
            "jti": claims.turn_id,
            "workspace_id": claims.workspace_id,
            "obo": claims.on_behalf_of,
        },
        _signing_key(),
        algorithm="HS256",
        headers={"kid": TURN_TOKEN_KID, "typ": "JWT"},
    )


def is_turn_token(token: str) -> bool:
    try:
        return jwt.get_unverified_header(token).get("kid") == TURN_TOKEN_KID
    except jwt.InvalidTokenError:
        return False


def decode_turn_token(token: str) -> TurnClaims | None:
    """The token's claims if it is signed by this platform and unexpired, else None."""
    try:
        audience = jwt.decode(token, options={"verify_signature": False}).get("aud")
        if not isinstance(audience, str) or not audience.startswith(_AUDIENCE_PREFIX):
            return None
        payload = jwt.decode(
            token,
            _signing_key(),
            algorithms=["HS256"],
            audience=audience,
            issuer=_ISSUER,
            options={"require": ["sub", "act", "aud", "exp", "jti"]},
        )
    except jwt.InvalidTokenError as exc:
        logger.info("Refused a turn token: %s", exc)
        return None
    actor_type, _, actor_id = str(payload["sub"]).partition(":")
    client = str((payload.get("act") or {}).get("sub", ""))
    if actor_type not in ("user", "agent") or not actor_id or not client.startswith(_CLIENT_PREFIX):
        logger.warning("Refused a turn token with malformed sub/act claims")
        return None
    return TurnClaims(
        turn_id=str(payload["jti"]),
        task_id=audience.removeprefix(_AUDIENCE_PREFIX),
        workspace_id=str(payload["workspace_id"]),
        client_id=client.removeprefix(_CLIENT_PREFIX),
        actor_type=actor_type,
        actor_id=actor_id,
        on_behalf_of=str(payload["obo"]),
    )


class LiveTurns:
    """The turns running now, by id, each alive while its runner heartbeats it."""

    def __init__(self, redis_url: str, *, prefix: str = "runners:live-turn") -> None:
        self._redis_url = redis_url
        self._prefix = prefix
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def _key(self, turn_id: str) -> str:
        return f"{self._prefix}:{turn_id}"

    async def begin(self, turn_id: str, ttl_seconds: int) -> None:
        client = await self._get_client()
        await client.set(self._key(turn_id), "1", ex=ttl_seconds)

    async def renew(self, turn_id: str, ttl_seconds: int) -> None:
        # Set again rather than extended, so a turn outlives a lapse while Redis was away.
        client = await self._get_client()
        await client.set(self._key(turn_id), "1", ex=ttl_seconds)

    async def end(self, turn_id: str) -> None:
        client = await self._get_client()
        await client.delete(self._key(turn_id))

    async def alive(self, turn_id: str) -> bool:
        client = await self._get_client()
        return bool(await client.exists(self._key(turn_id)))


_live_turns: LiveTurns | None = None


def live_turns() -> LiveTurns:
    """The process's live-turn store, on the broker's Redis."""
    global _live_turns
    if _live_turns is None:
        from ..config import RedisSettings, get_settings

        settings = get_settings()
        if not isinstance(settings.broker, RedisSettings):
            raise RuntimeError(
                "live runner turns are kept in Redis; set AGENTAREA_BROKER=redis "
                + f"(current: {settings.broker.BROKER})"
            )
        _live_turns = LiveTurns(settings.broker.REDIS_URL)
    return _live_turns
