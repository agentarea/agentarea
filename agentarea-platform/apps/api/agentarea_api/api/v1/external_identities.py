"""The caller's own messenger accounts: start a link, list them, unlink one.

A link is proven from both sides: the signed-in caller asks for a code here,
and the messenger account that opens the deep link has to confirm it in the
messenger (``agentarea_triggers.channels.sender_admission``). Nothing here
accepts an account id: typing one proves nothing about who holds it.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from agentarea_common.auth.dependencies import PrincipalDep, ensure_user_session
from agentarea_common.auth.route_authz import enforced_in_handler
from agentarea_common.config import RedisSettings, get_settings
from agentarea_common.config.database import get_db_session
from agentarea_common.identity import LINK_TTL_SECONDS, ExternalIdentityRepository, LinkCodes
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/me/external-identities", tags=["external-identities"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session, scope="function")]

_OWN_IDENTITY = "acts only on the caller's own links, keyed by their user id; API keys are refused"


class TelegramLinkRequest(BaseModel):
    # Telegram usernames: 5-32 letters, digits and underscores.
    bot: str = Field(pattern=r"^[A-Za-z0-9_]{5,32}$", description="The bot to open the link in")


class TelegramLinkResponse(BaseModel):
    url: str
    expires_in: int


class ExternalIdentityResponse(BaseModel):
    id: UUID
    provider: str
    external_id: str
    linked_at: datetime


def _redis_url() -> str:
    broker = get_settings().broker
    if not isinstance(broker, RedisSettings):
        raise HTTPException(status_code=503, detail="Account linking needs the Redis broker")
    return broker.REDIS_URL


@router.post(
    "/telegram/link",
    response_model=TelegramLinkResponse,
    dependencies=[enforced_in_handler(_OWN_IDENTITY)],
)
async def start_telegram_link(
    body: TelegramLinkRequest, user: PrincipalDep
) -> TelegramLinkResponse:
    """A deep link that offers the caller's account to whoever opens it in Telegram."""
    ensure_user_session(user, "link a messenger account")
    codes = LinkCodes(_redis_url())
    try:
        code = await codes.issue(user.user_id)
    finally:
        await codes.aclose()
    return TelegramLinkResponse(
        url=f"https://t.me/{body.bot}?start=link_{code}", expires_in=LINK_TTL_SECONDS
    )


@router.get(
    "",
    response_model=list[ExternalIdentityResponse],
    dependencies=[enforced_in_handler(_OWN_IDENTITY)],
)
async def list_external_identities(
    user: PrincipalDep, session: DatabaseSessionDep
) -> list[ExternalIdentityResponse]:
    links = await ExternalIdentityRepository(session).list_for_user(user.user_id)
    return [
        ExternalIdentityResponse(
            id=link.id,
            provider=link.provider,
            external_id=link.external_id,
            linked_at=link.created_at,
        )
        for link in links
    ]


@router.delete(
    "/{identity_id}",
    status_code=204,
    dependencies=[enforced_in_handler(_OWN_IDENTITY)],
)
async def unlink_external_identity(
    identity_id: UUID, user: PrincipalDep, session: DatabaseSessionDep
) -> Response:
    ensure_user_session(user, "unlink a messenger account")
    if not await ExternalIdentityRepository(session).revoke(
        user_id=user.user_id, identity_id=identity_id
    ):
        raise HTTPException(status_code=404, detail="No such linked account")
    return Response(status_code=204)
