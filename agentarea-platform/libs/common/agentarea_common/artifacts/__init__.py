"""Workspace-scoped artifact storage backed by S3 (RustFS in local dev).

Everything an agent writes — scratch files, generated images, tool outputs —
lives under ``workspaces/{workspace_id}/...`` in the artifacts bucket.
"""

from .audit import (
    ACTION_ARCHIVED,
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_MODIFIED,
    ACTION_MOVED,
    ACTOR_AGENT,
    ACTOR_USER,
    ArtifactActor,
    ArtifactEvent,
    ArtifactEventRecorder,
    DbArtifactEventRecorder,
)
from .content_security import (
    ACTIVE_CONTENT_TYPES,
    attachment_content_disposition,
    secure_download_headers,
)
from .service import (
    TRASH_PREFIX,
    ArtifactIntegrityError,
    ArtifactObject,
    ArtifactService,
)
from .workspace import (
    S3WorkspaceRepository,
    WorkspaceConflictError,
    WorkspaceEntry,
    WorkspaceError,
    WorkspaceManifest,
    WorkspaceManifestRef,
    WorkspaceObject,
    WorkspaceQuotaError,
    WorkspaceRepository,
    WorkspaceValidationError,
    normalize_workspace_path,
)

__all__ = [
    "ACTION_ARCHIVED",
    "ACTION_CREATED",
    "ACTION_DELETED",
    "ACTION_MODIFIED",
    "ACTION_MOVED",
    "ACTIVE_CONTENT_TYPES",
    "ACTOR_AGENT",
    "ACTOR_USER",
    "TRASH_PREFIX",
    "ArtifactActor",
    "ArtifactEvent",
    "ArtifactEventRecorder",
    "ArtifactIntegrityError",
    "ArtifactObject",
    "ArtifactService",
    "DbArtifactEventRecorder",
    "S3WorkspaceRepository",
    "WorkspaceConflictError",
    "WorkspaceEntry",
    "WorkspaceError",
    "WorkspaceManifest",
    "WorkspaceManifestRef",
    "WorkspaceObject",
    "WorkspaceQuotaError",
    "WorkspaceRepository",
    "WorkspaceValidationError",
    "attachment_content_disposition",
    "normalize_workspace_path",
    "secure_download_headers",
]
