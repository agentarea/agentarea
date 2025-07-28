"""Temporal-based artifact service implementation for ADK integration."""

import logging
from typing import Any, BinaryIO, Dict, List, Optional
from io import BytesIO

from ...ag.adk.artifacts.base_artifact_service import BaseArtifactService

logger = logging.getLogger(__name__)


class TemporalArtifactService(BaseArtifactService):
    """Artifact service that manages artifacts within Temporal workflow state.
    
    This implementation keeps artifacts in memory during workflow execution.
    For production use, this should be extended to persist to external storage.
    """
    
    def __init__(self):
        """Initialize the temporal artifact service."""
        self._artifacts: Dict[str, Dict[str, Any]] = {}
    
    async def upload_artifact(
        self,
        *,
        artifact_id: str,
        name: str,
        data: BinaryIO,
        content_type: Optional[str] = None,
    ) -> None:
        """Upload an artifact.
        
        Args:
            artifact_id: Unique identifier for the artifact
            name: Human-readable name for the artifact
            data: Binary data stream
            content_type: MIME type of the artifact
        """
        try:
            # Read the binary data
            if hasattr(data, 'read'):
                artifact_data = data.read()
            else:
                artifact_data = data
            
            # Store artifact metadata and data
            self._artifacts[artifact_id] = {
                "id": artifact_id,
                "name": name,
                "content_type": content_type or "application/octet-stream",
                "size": len(artifact_data),
                "data": artifact_data,
            }
            
            logger.info(f"Uploaded artifact: {artifact_id} ({name}) - {len(artifact_data)} bytes")
            
        except Exception as e:
            logger.error(f"Failed to upload artifact {artifact_id}: {e}")
            raise
    
    async def download_artifact(
        self, *, artifact_id: str
    ) -> Optional[BinaryIO]:
        """Download an artifact.
        
        Args:
            artifact_id: Unique identifier for the artifact
            
        Returns:
            Binary data stream or None if not found
        """
        artifact = self._artifacts.get(artifact_id)
        
        if artifact is None:
            logger.warning(f"Artifact not found: {artifact_id}")
            return None
        
        try:
            # Return data as BytesIO stream
            data_stream = BytesIO(artifact["data"])
            logger.debug(f"Downloaded artifact: {artifact_id}")
            return data_stream
            
        except Exception as e:
            logger.error(f"Failed to download artifact {artifact_id}: {e}")
            return None
    
    async def get_artifact_metadata(
        self, *, artifact_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get artifact metadata.
        
        Args:
            artifact_id: Unique identifier for the artifact
            
        Returns:
            Dictionary containing artifact metadata or None if not found
        """
        artifact = self._artifacts.get(artifact_id)
        
        if artifact is None:
            return None
        
        # Return metadata without the binary data
        metadata = {
            "id": artifact["id"],
            "name": artifact["name"],
            "content_type": artifact["content_type"],
            "size": artifact["size"],
        }
        
        logger.debug(f"Retrieved metadata for artifact: {artifact_id}")
        return metadata
    
    async def list_artifacts(self) -> List[Dict[str, Any]]:
        """List all artifacts.
        
        Returns:
            List of artifact metadata dictionaries
        """
        artifacts = []
        
        for artifact_id, artifact in self._artifacts.items():
            metadata = {
                "id": artifact["id"],
                "name": artifact["name"],
                "content_type": artifact["content_type"],
                "size": artifact["size"],
            }
            artifacts.append(metadata)
        
        logger.debug(f"Listed {len(artifacts)} artifacts")
        return artifacts
    
    async def delete_artifact(self, *, artifact_id: str) -> bool:
        """Delete an artifact.
        
        Args:
            artifact_id: Unique identifier for the artifact
            
        Returns:
            True if deleted, False if not found
        """
        if artifact_id in self._artifacts:
            del self._artifacts[artifact_id]
            logger.info(f"Deleted artifact: {artifact_id}")
            return True
        else:
            logger.warning(f"Attempted to delete non-existent artifact: {artifact_id}")
            return False
    
    def get_artifact_data(self) -> Dict[str, Any]:
        """Get current artifact data for Temporal workflow persistence.
        
        Returns:
            Dictionary containing artifact metadata (without binary data)
        """
        artifact_metadata = {}
        
        for artifact_id, artifact in self._artifacts.items():
            # Store metadata only, not binary data
            artifact_metadata[artifact_id] = {
                "id": artifact["id"],
                "name": artifact["name"],
                "content_type": artifact["content_type"],
                "size": artifact["size"],
                # Note: Binary data omitted for workflow state size management
            }
        
        return artifact_metadata
    
    def load_artifact_data(self, artifact_data: Dict[str, Any]) -> None:
        """Load artifact data from Temporal workflow state.
        
        Args:
            artifact_data: Dictionary containing artifact metadata
        """
        try:
            for artifact_id, metadata in artifact_data.items():
                # Create placeholder artifact with metadata only
                # Binary data would need to be loaded from external storage
                self._artifacts[artifact_id] = {
                    "id": metadata["id"],
                    "name": metadata["name"],
                    "content_type": metadata["content_type"],
                    "size": metadata["size"],
                    "data": b"",  # Placeholder - would load from storage in production
                }
            
            logger.info(f"Loaded {len(artifact_data)} artifact metadata entries")
            
        except Exception as e:
            logger.error(f"Failed to load artifact data: {e}")