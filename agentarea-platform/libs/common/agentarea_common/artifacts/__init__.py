"""Workspace-scoped artifact storage backed by S3 (RustFS in local dev).

Everything an agent writes — scratch files, generated images, tool outputs —
lives under ``workspaces/{workspace_id}/...`` in the artifacts bucket.
"""

from .service import ArtifactObject, ArtifactService

__all__ = ["ArtifactObject", "ArtifactService"]
