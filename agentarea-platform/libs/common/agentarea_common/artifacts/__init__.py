"""Workspace-scoped artifact storage backed by S3 (RustFS in local dev).

Everything an agent writes — scratch files, generated images, tool outputs —
lives under ``workspaces/{workspace_id}/...`` in the artifacts bucket.
"""

from .audit import (
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_MODIFIED,
    ACTOR_AGENT,
    ACTOR_USER,
    ArtifactActor,
    ArtifactEvent,
    ArtifactEventRecorder,
    DbArtifactEventRecorder,
)
from .service import ArtifactObject, ArtifactService

__all__ = [
    "ACTION_CREATED",
    "ACTION_DELETED",
    "ACTION_MODIFIED",
    "ACTOR_AGENT",
    "ACTOR_USER",
    "ArtifactActor",
    "ArtifactEvent",
    "ArtifactEventRecorder",
    "ArtifactObject",
    "ArtifactService",
    "DbArtifactEventRecorder",
]
