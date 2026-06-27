"""Provenance audit trail for workspace artifacts.

Every write/delete an artifact goes through ``ArtifactService`` can emit an
``ArtifactEvent`` recording *who* touched a file and *how* (created, modified,
deleted). The actor is either a human (``actor_type="user"``) acting through the
API, or an agent (``actor_type="agent"``) writing files mid-task — in which
case ``agent_id`` and ``task_id`` are filled so the UI can show which run
produced or changed the file.

Recording is best-effort: a failed audit write is logged loudly but never blocks
the underlying file operation (losing a file is worse than losing one history
row).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin

logger = logging.getLogger(__name__)

ACTION_CREATED = "created"
ACTION_MODIFIED = "modified"
ACTION_DELETED = "deleted"

ACTOR_USER = "user"
ACTOR_AGENT = "agent"


class ArtifactEvent(BaseModel, WorkspaceScopedMixin):
    """One provenance record for a workspace artifact path.

    ``created_by`` (from the mixin) is the user who owns the action — the
    uploader for ``user`` events, or the owner of the task for ``agent`` events.
    """

    __tablename__ = "artifact_events"

    path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


@dataclass(frozen=True)
class ArtifactActor:
    """Who is performing an artifact write/delete.

    For human API actions, ``user_id`` is the caller and ``actor_type`` is
    ``user``. For agent tool writes, ``user_id`` is the task owner, ``actor_type``
    is ``agent``, and ``agent_id``/``task_id`` identify the run.
    """

    user_id: str
    actor_type: str = ACTOR_USER
    agent_id: str | None = None
    task_id: str | None = None


class ArtifactEventRecorder(Protocol):
    """Sink for artifact provenance events."""

    async def record(
        self,
        *,
        workspace_id: str,
        path: str,
        action: str,
        actor: ArtifactActor,
    ) -> None: ...


class DbArtifactEventRecorder:
    """Persists artifact provenance events to the ``artifact_events`` table.

    Opens its own short-lived session (via the ``Database`` singleton) so it
    works identically from the API process and the Temporal worker, and never
    entangles itself with the caller's transaction.
    """

    async def record(
        self,
        *,
        workspace_id: str,
        path: str,
        action: str,
        actor: ArtifactActor,
    ) -> None:
        from agentarea_common.config.database import db

        event = ArtifactEvent(
            workspace_id=workspace_id,
            created_by=actor.user_id,
            path=path.lstrip("/"),
            action=action,
            actor_type=actor.actor_type,
            agent_id=actor.agent_id,
            task_id=actor.task_id,
        )
        async with db.session() as session:
            session.add(event)
