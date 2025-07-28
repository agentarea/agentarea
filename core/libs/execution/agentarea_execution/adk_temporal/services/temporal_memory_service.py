"""Temporal-based memory service implementation for ADK integration."""

import logging
from typing import Any, Dict, List, Optional

from ...ag.adk.memory.base_memory_service import BaseMemoryService
from ...ag.adk.memory.memory_entry import MemoryEntry

logger = logging.getLogger(__name__)


class TemporalMemoryService(BaseMemoryService):
    """Memory service that manages memory entries within Temporal workflow state.
    
    This implementation keeps memory data in memory during workflow execution.
    For production use, this should be extended to persist to external storage.
    """
    
    def __init__(self):
        """Initialize the temporal memory service."""
        self._memories: Dict[str, MemoryEntry] = {}
    
    async def create_memory_entry(
        self,
        *,
        entry_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        """Create a new memory entry.
        
        Args:
            entry_id: Unique identifier for the memory entry
            content: Content to store in memory
            metadata: Optional metadata dictionary
            
        Returns:
            Created MemoryEntry instance
        """
        try:
            # Create memory entry
            memory_entry = MemoryEntry(
                id=entry_id,
                content=content,
                metadata=metadata or {}
            )
            
            # Store in memory
            self._memories[entry_id] = memory_entry
            
            logger.info(f"Created memory entry: {entry_id}")
            return memory_entry
            
        except Exception as e:
            logger.error(f"Failed to create memory entry {entry_id}: {e}")
            raise
    
    async def get_memory_entry(
        self, *, entry_id: str
    ) -> Optional[MemoryEntry]:
        """Get a memory entry by ID.
        
        Args:
            entry_id: Unique identifier for the memory entry
            
        Returns:
            MemoryEntry instance or None if not found
        """
        memory_entry = self._memories.get(entry_id)
        
        if memory_entry is None:
            logger.warning(f"Memory entry not found: {entry_id}")
            return None
        
        logger.debug(f"Retrieved memory entry: {entry_id}")
        return memory_entry
    
    async def search_memory_entries(
        self,
        *,
        query: str,
        limit: Optional[int] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryEntry]:
        """Search memory entries by content and metadata.
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            metadata_filter: Optional metadata filter dictionary
            
        Returns:
            List of matching MemoryEntry instances
        """
        try:
            results = []
            query_lower = query.lower()
            
            for entry_id, memory_entry in self._memories.items():
                # Check content match
                content_match = query_lower in memory_entry.content.lower()
                
                # Check metadata filter
                metadata_match = True
                if metadata_filter:
                    for key, value in metadata_filter.items():
                        if key not in memory_entry.metadata or memory_entry.metadata[key] != value:
                            metadata_match = False
                            break
                
                # Add to results if both content and metadata match
                if content_match and metadata_match:
                    results.append(memory_entry)
            
            # Sort by relevance (simple: by content length for now)
            results.sort(key=lambda x: len(x.content))
            
            # Apply limit
            if limit is not None:
                results = results[:limit]
            
            logger.debug(f"Search for '{query}' returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"Memory search failed for query '{query}': {e}")
            return []
    
    async def update_memory_entry(
        self,
        *,
        entry_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[MemoryEntry]:
        """Update an existing memory entry.
        
        Args:
            entry_id: Unique identifier for the memory entry
            content: New content (optional)
            metadata: New metadata (optional)
            
        Returns:
            Updated MemoryEntry instance or None if not found
        """
        memory_entry = self._memories.get(entry_id)
        
        if memory_entry is None:
            logger.warning(f"Cannot update non-existent memory entry: {entry_id}")
            return None
        
        try:
            # Update content if provided
            if content is not None:
                memory_entry.content = content
            
            # Update metadata if provided
            if metadata is not None:
                memory_entry.metadata.update(metadata)
            
            logger.info(f"Updated memory entry: {entry_id}")
            return memory_entry
            
        except Exception as e:
            logger.error(f"Failed to update memory entry {entry_id}: {e}")
            return None
    
    async def delete_memory_entry(self, *, entry_id: str) -> bool:
        """Delete a memory entry.
        
        Args:
            entry_id: Unique identifier for the memory entry
            
        Returns:
            True if deleted, False if not found
        """
        if entry_id in self._memories:
            del self._memories[entry_id]
            logger.info(f"Deleted memory entry: {entry_id}")
            return True
        else:
            logger.warning(f"Attempted to delete non-existent memory entry: {entry_id}")
            return False
    
    async def list_memory_entries(
        self,
        *,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[MemoryEntry]:
        """List all memory entries.
        
        Args:
            limit: Maximum number of entries to return
            offset: Number of entries to skip
            
        Returns:
            List of MemoryEntry instances
        """
        try:
            # Get all entries sorted by ID
            all_entries = list(self._memories.values())
            all_entries.sort(key=lambda x: x.id)
            
            # Apply offset
            if offset is not None:
                all_entries = all_entries[offset:]
            
            # Apply limit
            if limit is not None:
                all_entries = all_entries[:limit]
            
            logger.debug(f"Listed {len(all_entries)} memory entries")
            return all_entries
            
        except Exception as e:
            logger.error(f"Failed to list memory entries: {e}")
            return []
    
    def get_memory_data(self) -> Dict[str, Any]:
        """Get current memory data for Temporal workflow persistence.
        
        Returns:
            Dictionary containing memory data
        """
        memory_data = {}
        
        for entry_id, memory_entry in self._memories.items():
            memory_data[entry_id] = {
                "id": memory_entry.id,
                "content": memory_entry.content,
                "metadata": memory_entry.metadata,
            }
        
        return memory_data
    
    def load_memory_data(self, memory_data: Dict[str, Any]) -> None:
        """Load memory data from Temporal workflow state.
        
        Args:
            memory_data: Dictionary containing memory data
        """
        try:
            for entry_id, entry_data in memory_data.items():
                memory_entry = MemoryEntry(
                    id=entry_data["id"],
                    content=entry_data["content"],
                    metadata=entry_data.get("metadata", {})
                )
                self._memories[entry_id] = memory_entry
            
            logger.info(f"Loaded {len(memory_data)} memory entries")
            
        except Exception as e:
            logger.error(f"Failed to load memory data: {e}")