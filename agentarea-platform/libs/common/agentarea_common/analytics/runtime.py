"""This process's analytics sender, started with the api or the worker.

The one handle counters reach the sender through. It is None while analytics is
off and outside a started process, and then nothing is counted or sent.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentarea_common.config import get_settings

from .repository import get_or_create_installation
from .sender import AnalyticsSender

logger = logging.getLogger(__name__)

_sender: AnalyticsSender | None = None


def current_sender() -> AnalyticsSender | None:
    return _sender


async def start_analytics(
    session_factory: async_sessionmaker[AsyncSession],
) -> AnalyticsSender | None:
    """Start sending as this installation; None, and nothing constructed, when analytics is off.

    Never fails the process starting it: if analytics cannot start, it stays off for it.
    """
    global _sender
    if not get_settings().analytics.ENABLED:
        return None
    try:
        async with session_factory() as session:
            installation = await get_or_create_installation(session)
            await session.commit()
        sender = AnalyticsSender(enabled=True, install_id=installation.id)
        await sender.start()
    except Exception:
        logger.error("Usage analytics could not start; it is off for this process", exc_info=True)
        return None
    _sender = sender
    return sender


async def stop_analytics() -> None:
    """Stop counting and send what is left."""
    global _sender
    sender, _sender = _sender, None
    if sender is not None:
        await sender.stop()
