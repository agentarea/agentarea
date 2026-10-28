"""Writes of sign-up attributions."""

from dataclasses import asdict
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .attribution import Attribution
from .signup_models import SignupAttribution


async def upsert_signup_attribution(
    session: AsyncSession,
    *,
    identity_id: str,
    created_at: datetime,
    method: str | None,
    attribution: Attribution,
) -> bool:
    """Store the identity's attribution once; True when this call inserted it. The caller commits."""
    now = datetime.now()
    inserted = await session.execute(
        insert(SignupAttribution)
        .values(
            identity_id=identity_id,
            created_at=created_at,
            updated_at=now,
            method=method,
            **asdict(attribution),
        )
        .on_conflict_do_nothing(index_elements=[SignupAttribution.identity_id])
        .returning(SignupAttribution.identity_id)
    )
    return inserted.scalar_one_or_none() is not None
