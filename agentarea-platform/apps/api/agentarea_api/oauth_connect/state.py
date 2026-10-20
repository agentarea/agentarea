"""OAuth state between authorize, the callback and the finish.

The state token is the only credential the public callback has. Its payload
names the connection the flow is for, never a client secret: those sit on the
auth config the authorize step already persisted.

The callback does not redeem the code: anyone can open a provider URL someone
else's authorize returned. It parks the code under a finish token, and the
person who started the flow redeems it from their own session.
"""

import json
import logging
from dataclasses import asdict, dataclass
from typing import Literal

from agentarea_common.infrastructure.connection_manager import get_connection_manager
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_PREFIX = "oauth_state"
_RETURNED_PREFIX = "oauth_returned"
_TTL_SECONDS = 600

TargetKind = Literal["mcp_instance", "openapi_connection"]


@dataclass(frozen=True)
class OAuthState:
    target_kind: TargetKind
    connection_id: str
    auth_config_id: str
    workspace_id: str
    user_id: str
    code_verifier: str
    return_to: str = ""


async def _redis():
    from agentarea_common.events.redis_event_broker import RedisEventBroker

    broker = await get_connection_manager().get_event_broker()
    if isinstance(broker, RedisEventBroker):
        await broker._ensure_connected()
        if broker.raw_redis is not None:
            return broker.raw_redis
    raise HTTPException(status_code=500, detail="Redis not available")


async def store(token: str, state: OAuthState) -> None:
    redis = await _redis()
    await redis.set(f"{_PREFIX}:{token}", json.dumps(asdict(state)), ex=_TTL_SECONDS)


async def pop(token: str) -> OAuthState | None:
    """The state for ``token``, consumed so a replayed callback cannot redeem a code twice."""
    redis = await _redis()
    raw = await redis.getdel(f"{_PREFIX}:{token}")
    if raw is None:
        return None
    return OAuthState(**json.loads(raw))


@dataclass(frozen=True)
class ReturnedFlow:
    """A flow the provider sent back with a code, waiting for its starter to finish it."""

    flow: OAuthState
    code: str


async def store_returned(token: str, returned: ReturnedFlow) -> None:
    redis = await _redis()
    payload = {"flow": asdict(returned.flow), "code": returned.code}
    await redis.set(f"{_RETURNED_PREFIX}:{token}", json.dumps(payload), ex=_TTL_SECONDS)


async def pop_returned(token: str) -> ReturnedFlow | None:
    """The returned flow for ``token``, consumed whoever asks: a refused finish is final."""
    redis = await _redis()
    raw = await redis.getdel(f"{_RETURNED_PREFIX}:{token}")
    if raw is None:
        return None
    payload = json.loads(raw)
    return ReturnedFlow(flow=OAuthState(**payload["flow"]), code=payload["code"])
