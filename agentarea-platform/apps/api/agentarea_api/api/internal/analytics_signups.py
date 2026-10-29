"""Kratos's after-registration hook: which channel brought each sign-up (wiki ADR-0047).

Mounted outside /v1 and left out of the public API schema: its only caller is
Kratos, authenticated by AGENTAREA_ANALYTICS_SIGNUP_HOOK_KEY. Unset, it answers 404.
"""

import hmac
from datetime import UTC, datetime
from typing import Annotated

from agentarea_common.analytics import current_sender, get_or_create_installation, pseudonymize
from agentarea_common.analytics.attribution import attribution_from_request_url
from agentarea_common.analytics.signup_repository import upsert_signup_attribution
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.config import get_settings
from agentarea_common.config.database import get_db_session
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/internal/analytics", tags=["internal"], include_in_schema=False)

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session, scope="function")]

METHODS = frozenset({"password", "oidc", "code"})


class SignupHook(BaseModel):
    identity_id: str = Field(min_length=1, max_length=64)
    created_at: datetime
    request_url: str | None = None


async def _hook_key(authorization: Annotated[str | None, Header()] = None) -> None:
    key = get_settings().analytics.SIGNUP_HOOK_KEY
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not hmac.compare_digest((authorization or "").encode(), key.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@router.post(
    "/signups",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        unrestricted("Kratos's registration hook; authenticated by the shared signup hook key"),
        Depends(_hook_key),
    ],
)
async def record_signup(
    hook: SignupHook, session: DatabaseSessionDep, method: str | None = None
) -> Response:
    """Store the sign-up's channel once per identity; the first store also sends ``sign_up``."""
    method = method if method in METHODS else None
    attribution = attribution_from_request_url(hook.request_url)
    created_at = hook.created_at.astimezone(UTC).replace(tzinfo=None)
    inserted = await upsert_signup_attribution(
        session,
        identity_id=hook.identity_id,
        created_at=created_at,
        method=method,
        attribution=attribution,
    )
    sender = current_sender()
    if not (inserted and sender is not None and get_settings().analytics.ENABLED):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    installation = await get_or_create_installation(session)
    await session.commit()
    sender.enqueue(
        {
            "event": "sign_up",
            "user_id": pseudonymize(installation.id, hook.identity_id),
            "properties": {
                "channel": attribution.channel,
                "method": method,
                "landing_host": attribution.landing_host,
                "landing_path": attribution.landing_path,
                "referrer_host": attribution.referrer_host,
                "utm_source": attribution.utm_source,
                "utm_medium": attribution.utm_medium,
                "utm_campaign": attribution.utm_campaign,
            },
        }
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
