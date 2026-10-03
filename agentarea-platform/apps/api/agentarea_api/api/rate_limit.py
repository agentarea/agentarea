"""Valkey-backed token-bucket limits for public API surfaces."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable
from typing import cast

import redis.asyncio as redis
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import get_optional_principal
from agentarea_common.config import get_settings
from fastapi import Depends, HTTPException, Request
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_TOKEN_BUCKET_TTL_SECONDS = 120
_OAUTH_REGISTRATION_LIMIT_PER_MINUTE = 10
_A2A_RPC_LIMIT_PER_MINUTE = 300
_RATE_LIMIT_LUA = """
local capacity = tonumber(ARGV[1])
if not capacity or capacity <= 0 then
    return {0, 60}
end

local time = redis.call('TIME')
local now = tonumber(time[1]) + tonumber(time[2]) / 1000000
local refill_per_second = capacity / 60
local state = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local tokens = tonumber(state[1]) or capacity
local updated_at = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - updated_at) * refill_per_second)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    retry_after = math.max(1, math.ceil((1 - tokens) / refill_per_second))
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', KEYS[1], ARGV[2])
return {allowed, retry_after}
"""

_rate_limit_redis: redis.Redis | None = None


def _get_redis_client() -> redis.Redis:
    global _rate_limit_redis
    if _rate_limit_redis is None:
        _rate_limit_redis = redis.from_url(
            get_settings().mcp.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _rate_limit_redis


async def close_rate_limit_client() -> None:
    global _rate_limit_redis
    if _rate_limit_redis is not None:
        await _rate_limit_redis.aclose()
        _rate_limit_redis = None


async def enforce_rate_limit(*, scope: str, identity: str, limit: int) -> None:
    identity_hash = hashlib.sha256(identity.encode()).hexdigest()
    redis_key = f"agentarea:rate-limit:{scope}:{identity_hash}"

    try:
        # redis-py types its sync and asyncio clients together (``Awaitable[str] | str``);
        # the asyncio client always returns an awaitable, and the script returns a pair.
        result = await cast(
            "Awaitable[list[int]]",
            _get_redis_client().eval(
                _RATE_LIMIT_LUA,
                1,
                redis_key,
                limit,
                _TOKEN_BUCKET_TTL_SECONDS,
            ),
        )
        allowed, retry_after = int(result[0]), int(result[1])
    except RedisError:
        logger.warning("Rate-limit Redis unavailable; allowing request", exc_info=True)
        return

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(retry_after, 1))},
        )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


async def limit_webhook(webhook_id: str) -> None:
    await enforce_rate_limit(
        scope="webhook",
        identity=webhook_id,
        limit=get_settings().triggers.WEBHOOK_RATE_LIMIT_PER_MINUTE,
    )


async def limit_oauth_registration(request: Request) -> None:
    await enforce_rate_limit(
        scope="oauth-registration",
        identity=_client_ip(request),
        limit=_OAUTH_REGISTRATION_LIMIT_PER_MINUTE,
    )


async def limit_a2a_rpc(
    request: Request,
    subject: UserPrincipal | None = Depends(get_optional_principal),
) -> None:
    """One bucket per caller: the API key or user that authenticated, else the IP.

    Agent-to-agent delegation reaches this endpoint from the worker, so every
    workspace's delegations arrive from one address; an IP bucket would let
    one busy workspace refuse everyone else's calls.
    """
    if subject is None:
        identity = f"ip:{_client_ip(request)}"
    elif subject.api_key_id is not None:
        identity = f"api-key:{subject.api_key_id}"
    else:
        identity = f"user:{subject.user_id}"
    await enforce_rate_limit(scope="a2a-rpc", identity=identity, limit=_A2A_RPC_LIMIT_PER_MINUTE)
