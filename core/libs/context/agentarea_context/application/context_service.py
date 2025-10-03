from uuid import UUID

from agentarea_context.domain.enums import ContextType
from agentarea_context.domain.interfaces import ContextProvider
from agentarea_context.domain.models import Context


class ContextService:
    def __init__(self, context_provider: ContextProvider):
        self.context_provider = context_provider

    async def store_context(
        self,
        content: str,
        context_type: ContextType = ContextType.FACTUAL,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> UUID:
        """Store context with flexible scope identifiers."""
        return await self.context_provider.store_context(
            content=content,
            context_type=context_type,
            task_id=task_id,
            agent_id=agent_id,
            metadata=metadata or {},
        )

    async def get_context(
        self,
        query: str,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        limit: int = 10,
    ) -> list[Context]:
        """Retrieve context based on query and optional scope filters."""
        return await self.context_provider.get_context(
            query=query, task_id=task_id, agent_id=agent_id, limit=limit
        )

    async def delete_context(self, context_id: UUID) -> bool:
        """Delete a specific context entry."""
        return await self.context_provider.delete_context(context_id)

    async def update_context(self, context_id: UUID, content: str) -> Context:
        """Update the content of a specific context entry."""
        return await self.context_provider.update_context(context_id, content)

    async def get_task_context(self, task_id: UUID, query: str, limit: int = 10) -> list[Context]:
        """Get context specific to a task."""
        return await self.get_context(query=query, task_id=task_id, limit=limit)

    async def get_agent_context(self, agent_id: UUID, query: str, limit: int = 10) -> list[Context]:
        """Get context specific to an agent."""
        return await self.get_context(query=query, agent_id=agent_id, limit=limit)

    async def get_combined_context(
        self, task_id: UUID, agent_id: UUID, query: str, limit: int = 10
    ) -> list[Context]:
        """Get hierarchical context combining task and agent scopes."""
        # Get task-specific context first (highest priority)
        task_contexts = await self.get_context(query=query, task_id=task_id, limit=limit // 2)

        # Get agent-specific context
        agent_contexts = await self.get_context(query=query, agent_id=agent_id, limit=limit // 2)

        # Combine and deduplicate by context ID
        all_contexts = task_contexts + agent_contexts
        seen_ids = set()
        unique_contexts = []

        for context in all_contexts:
            if context.id not in seen_ids:
                seen_ids.add(context.id)
                unique_contexts.append(context)

        # Sort by relevance score (highest first) and limit results
        unique_contexts.sort(key=lambda c: c.score or 0, reverse=True)
        return unique_contexts[:limit]
