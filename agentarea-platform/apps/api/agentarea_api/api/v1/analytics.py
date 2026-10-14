"""Whether this installation reports usage analytics, for the webapp to follow.

The webapp reads no variable of its own: it asks here, so the backend and the UI
cannot disagree about AGENTAREA_ANALYTICS_ENABLED.
"""

from typing import Annotated

from agentarea_common.analytics import COLLECTOR_KEY, COLLECTOR_URL, get_or_create_installation
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.config import get_app_settings, get_settings
from agentarea_common.config.database import get_db_session
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/analytics", tags=["analytics"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session, scope="function")]


class AnalyticsResponse(BaseModel):
    enabled: bool
    # All four are null when analytics is off.
    install_id: str | None
    collector_url: str | None
    collector_key: str | None
    # The edition every event's context carries (AGENTAREA_EDITION).
    edition: str | None


@router.get(
    "",
    response_model=AnalyticsResponse,
    dependencies=[
        unrestricted("deployment-wide analytics switch and anonymous install id; no workspace data")
    ],
)
async def get_analytics(session: DatabaseSessionDep) -> AnalyticsResponse:
    """Return whether analytics is on and, if so, where and as which installation to send."""
    if not get_settings().analytics.ENABLED:
        return AnalyticsResponse(
            enabled=False, install_id=None, collector_url=None, collector_key=None, edition=None
        )
    installation = await get_or_create_installation(session)
    return AnalyticsResponse(
        enabled=True,
        install_id=installation.id,
        collector_url=COLLECTOR_URL,
        collector_key=COLLECTOR_KEY,
        edition=get_app_settings().EDITION,
    )
