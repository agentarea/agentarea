"""Reads and writes of the installation row."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Installation


async def get_or_create_installation(session: AsyncSession) -> Installation:
    """The installation row, created on first use. The caller commits.

    Replicas starting together all insert; the single-row index lets one win and
    the rest read its row.
    """
    await session.execute(insert(Installation).values(id=uuid4().hex).on_conflict_do_nothing())
    return (await session.execute(select(Installation))).scalar_one()
