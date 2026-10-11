"""Reads and writes of external identity links."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import UserExternalIdentity


class ExternalIdentityTakenError(Exception):
    """The account is already linked to another user."""


class ExternalIdentityRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def holder(self, provider: str, external_id: str) -> str | None:
        """The user an account is linked to, if any."""
        result = await self._session.execute(
            select(UserExternalIdentity.user_id).where(
                UserExternalIdentity.provider == provider,
                UserExternalIdentity.external_id == external_id,
                UserExternalIdentity.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def link(
        self, *, user_id: str, provider: str, external_id: str, method: str
    ) -> UserExternalIdentity:
        """Link an account to ``user_id``; linking it again to the same user is a no-op.

        Raises:
            ExternalIdentityTakenError: Another user holds the account. They
                have to unlink it first; it is never moved silently.
        """
        result = await self._session.execute(
            select(UserExternalIdentity).where(
                UserExternalIdentity.provider == provider,
                UserExternalIdentity.external_id == external_id,
                UserExternalIdentity.revoked_at.is_(None),
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            if existing.user_id != user_id:
                raise ExternalIdentityTakenError(f"{provider} account is linked to another user")
            return existing
        link = UserExternalIdentity(
            user_id=user_id, provider=provider, external_id=external_id, method=method
        )
        self._session.add(link)
        await self._session.commit()
        await self._session.refresh(link)
        return link

    async def list_for_user(self, user_id: str) -> list[UserExternalIdentity]:
        result = await self._session.execute(
            select(UserExternalIdentity)
            .where(
                UserExternalIdentity.user_id == user_id,
                UserExternalIdentity.revoked_at.is_(None),
            )
            .order_by(UserExternalIdentity.created_at)
        )
        return list(result.scalars().all())

    async def revoke(self, *, user_id: str, identity_id: UUID) -> bool:
        """Unlink one of ``user_id``'s accounts; returns whether it was theirs and live."""
        result = await self._session.execute(
            select(UserExternalIdentity).where(
                UserExternalIdentity.id == identity_id,
                UserExternalIdentity.user_id == user_id,
                UserExternalIdentity.revoked_at.is_(None),
            )
        )
        link = result.scalar_one_or_none()
        if link is None:
            return False
        link.revoked_at = datetime.now()
        await self._session.commit()
        return True
