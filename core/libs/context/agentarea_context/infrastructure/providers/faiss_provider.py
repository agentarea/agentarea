import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import faiss
import numpy as np
from agentarea_llm.application.embedding_service import EmbeddingService

from agentarea_context.config.context_config import ContextConfig
from agentarea_context.domain.enums import ContextType
from agentarea_context.domain.interfaces import ContextProvider
from agentarea_context.domain.models import Context


class FAISSContextProvider(ContextProvider):
    def __init__(
        self, config: ContextConfig, embedding_service: EmbeddingService, model_instance_id: UUID
    ):
        self.config = config
        self.embedding_service = embedding_service
        self.model_instance_id = model_instance_id
        self.index: faiss.Index | None = None
        self.metadata: dict[int, dict[str, Any]] = {}
        # Note: _load_or_create_index is now async and called separately

    async def _load_or_create_index(self):
        index_path = Path(self.config.faiss_index_path)
        metadata_path = Path(self.config.faiss_metadata_path)

        # Create directories if they don't exist
        index_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        if index_path.exists() and metadata_path.exists():
            # Load existing index
            self.index = faiss.read_index(str(index_path))
            with open(metadata_path) as f:
                raw_metadata = json.load(f)
                # Convert string keys back to int
                self.metadata = {int(k): v for k, v in raw_metadata.items()}
        else:
            # Create new index using embedding service dimension
            embedding_dim = await self.embedding_service.get_embedding_dimension(
                self.model_instance_id
            )
            self.index = faiss.IndexFlatIP(embedding_dim)
            self.metadata = {}

    def _save_index(self):
        index_path = Path(self.config.faiss_index_path)
        metadata_path = Path(self.config.faiss_metadata_path)

        faiss.write_index(self.index, str(index_path))
        with open(metadata_path, "w") as f:
            # Convert int keys to string for JSON serialization
            serializable_metadata = {str(k): v for k, v in self.metadata.items()}
            json.dump(serializable_metadata, f, default=str, indent=2)

    def _create_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def _context_matches_filter(
        self,
        context_meta: dict[str, Any],
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> bool:
        # If no filters provided, match everything
        if task_id is None and agent_id is None:
            return True

        # Check each filter - all provided filters must match
        if task_id is not None and context_meta.get("task_id") != str(task_id):
            return False
        if agent_id is not None and context_meta.get("agent_id") != str(agent_id):
            return False

        return True

    async def store_context(
        self,
        content: str,
        context_type: ContextType = ContextType.FACTUAL,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> UUID:
        # Ensure index is initialized
        if self.index is None:
            await self._load_or_create_index()

        # Generate embedding using the embedding service
        embeddings = await self.embedding_service.generate_embeddings(
            [content], self.model_instance_id
        )
        embedding = np.array(embeddings[0], dtype=np.float32)

        # Normalize for cosine similarity (IndexFlatIP expects normalized vectors)
        embedding = embedding.reshape(1, -1)
        faiss.normalize_L2(embedding)

        # Generate context ID and get index position
        context_id = uuid4()
        index_position = self.index.ntotal

        # Store in FAISS index
        self.index.add(embedding)

        # Store metadata
        context_metadata = {
            "context_id": str(context_id),
            "content": content,
            "context_type": context_type.value,
            "task_id": str(task_id) if task_id else None,
            "agent_id": str(agent_id) if agent_id else None,
            "metadata": metadata or {},
            "content_hash": self._create_content_hash(content),
        }

        self.metadata[index_position] = context_metadata

        # Save to disk
        self._save_index()

        return context_id

    async def get_context(
        self,
        query: str,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        limit: int = 10,
    ) -> list[Context]:
        if self.index.ntotal == 0:
            return []

        # Ensure index is initialized
        if self.index is None:
            await self._load_or_create_index()

        # Generate query embedding using the embedding service
        query_embeddings = await self.embedding_service.generate_embeddings(
            [query], self.model_instance_id
        )
        query_embedding = np.array(query_embeddings[0], dtype=np.float32)
        query_embedding = query_embedding.reshape(1, -1)
        faiss.normalize_L2(query_embedding)

        # Search for similar contexts
        # Get more results than needed for filtering
        search_limit = min(limit * 3, self.index.ntotal)
        scores, indices = self.index.search(query_embedding, search_limit)

        contexts = []
        for score, idx in zip(scores[0], indices[0], strict=False):
            if idx == -1:  # No more results
                break

            context_meta = self.metadata.get(idx)
            if context_meta is None:
                continue

            # Apply filters
            if not self._context_matches_filter(context_meta, task_id, agent_id):
                continue

            # Convert back to Context model
            context = Context(
                id=UUID(context_meta["context_id"]),
                content=context_meta["content"],
                context_type=ContextType(context_meta["context_type"]),
                task_id=UUID(context_meta["task_id"]) if context_meta["task_id"] else None,
                agent_id=UUID(context_meta["agent_id"]) if context_meta["agent_id"] else None,
                context_metadata=context_meta["metadata"],
                score=float(score),
            )

            contexts.append(context)

            if len(contexts) >= limit:
                break

        return contexts

    async def delete_context(self, context_id: UUID) -> bool:
        # Find the context in metadata
        index_position = None
        for idx, meta in self.metadata.items():
            if meta["context_id"] == str(context_id):
                index_position = idx
                break

        if index_position is None:
            return False

        # Remove from metadata
        del self.metadata[index_position]

        # Note: FAISS doesn't support efficient deletion of individual vectors
        # For now, we just remove from metadata (the vector remains but won't be returned)
        # In production, you might want to periodically rebuild the index

        self._save_index()
        return True

    async def update_context(self, context_id: UUID, content: str) -> Context:
        # Find the context
        index_position = None
        for idx, meta in self.metadata.items():
            if meta["context_id"] == str(context_id):
                index_position = idx
                break

        if index_position is None:
            raise ValueError(f"Context with ID {context_id} not found")

        # Update metadata
        old_meta = self.metadata[index_position]
        old_meta["content"] = content
        old_meta["content_hash"] = self._create_content_hash(content)

        # Generate new embedding
        embeddings = await self.embedding_service.generate_embeddings(
            [content], self.model_instance_id
        )
        embedding = np.array(embeddings[0], dtype=np.float32)
        embedding = embedding.reshape(1, -1)
        faiss.normalize_L2(embedding)

        # Note: FAISS doesn't support efficient updates
        # For simplicity, we'll just update metadata and keep old embedding
        # In production, consider rebuilding index or using a different approach

        self._save_index()

        return Context(
            id=UUID(old_meta["context_id"]),
            content=old_meta["content"],
            context_type=ContextType(old_meta["context_type"]),
            task_id=UUID(old_meta["task_id"]) if old_meta["task_id"] else None,
            agent_id=UUID(old_meta["agent_id"]) if old_meta["agent_id"] else None,
            context_metadata=old_meta["metadata"],
        )
