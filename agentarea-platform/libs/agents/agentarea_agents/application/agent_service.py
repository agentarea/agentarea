import logging
from typing import Any, cast
from uuid import UUID

from agentarea_common.audit import audited
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.service import BaseCrudService
from agentarea_common.events.broker import EventBroker
from agentarea_common.utils.slug import generate_slug

from agentarea_agents.domain.events import AgentCreated, AgentDeleted, AgentUpdated
from agentarea_agents.domain.models import Agent
from agentarea_agents.infrastructure.catalog_agent_repository import (
    CatalogAgentItem,
    CatalogAgentRepository,
    pick_model_instance_id,
)
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate

logger = logging.getLogger(__name__)


def _preferred_models_from_spec(spec: dict[str, Any]) -> list[str]:
    """Read a catalog agent's preferred model slugs (priority order) from its spec.

    The catalog is global, so it carries model *preferences* (slugs), never a
    concrete ``model_id`` (which is a per-workspace model-instance UUID). Older,
    not-yet-resynced catalog specs stored a single slug under ``model_id``; accept
    that as a one-element fallback.
    """
    preferred = spec.get("preferred_models")
    if isinstance(preferred, list):
        return [m for m in preferred if isinstance(m, str) and m]
    legacy = spec.get("model_id")
    if isinstance(legacy, str) and legacy:
        return [legacy]
    return []


def _project_catalog_item(item: CatalogAgentItem, model_id: str | None = None) -> Agent:
    """Project a catalog agent item into a transient, read-only ``Agent``.

    The projected agent is NOT persisted. Its ``id`` is the catalog item's id so
    the read/update paths can resolve it back to the registry item. The catalog
    metadata (``is_catalog``, ``registry_item_id``, ``update_available``) is
    attached as plain attributes for the API layer to surface.

    ``model_id`` is the per-workspace model instance resolved from the item's
    preferred models, or ``None`` when no configured instance matches.
    """
    spec = item.spec or {}
    tools = spec.get("tools")
    if not isinstance(tools, list):
        tools = None

    agent = Agent(
        id=UUID(item.id),
        name=item.name,
        slug=generate_slug(item.name),
        status="active",
        description=item.description if item.description is not None else spec.get("description"),
        instruction=spec.get("instruction"),
        model_id=model_id,
        tools=tools,
        events_config=spec.get("events_config"),
        planning=spec.get("planning"),
        a2ui_enabled=False,
        agent_type="stateless",
        registry_item_id=item.id,
    )
    # Read-only catalog projection markers consumed by the API DTO.
    agent.is_catalog = True  # type: ignore[attr-defined]
    agent.update_available = False  # type: ignore[attr-defined]
    return agent


class AgentService(BaseCrudService[Agent]):
    def __init__(
        self,
        repository_factory: RepositoryFactory,
        event_broker: EventBroker,
        authorization_service: AuthorizationService,
    ):
        repository = repository_factory.create_repository(AgentRepository)
        super().__init__(repository)
        self.repository_factory = repository_factory
        self.event_broker = event_broker
        self._user_context = repository_factory.user_context
        self._authz = authorization_service

    async def _check_write_access(self, agent: Agent) -> None:
        """Check if the current user can mutate this agent.

        Raises:
            PermissionError: If the user cannot write to the agent's workspace.
        """
        if not await self._authz.can_write_workspace(self._user_context, agent.workspace_id):
            raise PermissionError(f"Cannot modify agent in workspace '{agent.workspace_id}'")

    def _get_agent_repository(self) -> AgentRepository:
        """Get the agent repository with proper type."""
        return self.repository_factory.create_repository(AgentRepository)

    def _get_catalog_repository(self) -> CatalogAgentRepository:
        """Get the read-only catalog (registry_items) repository for agents."""
        return CatalogAgentRepository(
            session=self.repository_factory.session,
            user_context=self._user_context,
        )

    async def list(self, include_catalog: bool = False) -> list[Agent]:  # type: ignore[override]
        """List the workspace's own agents.

        Catalog (built-in) agents live in the registry and are discovered via
        Explore — they are NOT part of the working set, so they are excluded by
        default. Pass ``include_catalog=True`` to also project unforked catalog
        items as read-only (ADR-003).

        Forked copies (a tenant ``agents`` row carrying ``registry_item_id``) are
        always flagged ``update_available`` when the catalog version has moved on
        from the version recorded at fork time.
        """
        repo = self._get_agent_repository()
        tenant_agents = await repo.list_all()

        catalog_repo = self._get_catalog_repository()
        catalog_items = await catalog_repo.list_items()
        forked_by_item: dict[str, Agent] = {
            str(a.registry_item_id): a
            for a in tenant_agents
            if getattr(a, "registry_item_id", None)
        }
        for item in catalog_items:
            forked = forked_by_item.get(item.id)
            if forked is not None and item.version and item.version != item.installed_version:
                forked.update_available = True  # type: ignore[attr-defined]

        if not include_catalog:
            return list(tenant_agents)

        instance_ids_by_name = await catalog_repo.model_instance_ids_by_name()
        result: list[Agent] = list(tenant_agents)
        for item in catalog_items:
            if item.id not in forked_by_item:
                model_id = pick_model_instance_id(
                    _preferred_models_from_spec(item.spec or {}), instance_ids_by_name
                )
                result.append(_project_catalog_item(item, model_id))
        return result

    async def get_with_catalog(self, id: UUID) -> Agent | None:
        """Get a tenant agent by id, falling back to a catalog projection.

        Returns the tenant ``agents`` row if present; otherwise projects the
        matching catalog ``registry_item`` (read-only). No DB row is created.
        """
        agent = await self.get(id)
        if agent is not None:
            return agent
        catalog_repo = self._get_catalog_repository()
        item = await catalog_repo.get_item(str(id))
        if item is None:
            return None
        model_id = await catalog_repo.resolve_model_instance_id(
            _preferred_models_from_spec(item.spec or {})
        )
        return _project_catalog_item(item, model_id)

    async def _resolve_unique_slug(self, name: str) -> str:
        """Generate a workspace-unique slug from ``name``.

        Tries ``base``, then ``base-2``, ``base-3``, ... up to ``base-999``.
        """
        repo = self._get_agent_repository()
        base = generate_slug(name)

        if await repo.get_by_slug(base) is None:
            return base

        for suffix in range(2, 1000):
            candidate = f"{base}-{suffix}"
            if await repo.get_by_slug(candidate) is None:
                return candidate

        raise ValueError(f"Exhausted collision suffixes (-2..-999) for slug base '{base}'")

    @audited("agent.create", resource_type="agent")
    async def create_agent(self, payload: AgentCreate) -> Agent:
        tools = [t.model_dump(exclude_none=True) for t in payload.tools] if payload.tools else None
        events_config = payload.events_config.model_dump() if payload.events_config else None

        slug = await self._resolve_unique_slug(payload.name)

        agent = Agent(
            name=payload.name,
            slug=slug,
            description=payload.description,
            instruction=payload.instruction,
            model_id=payload.model_id,
            tools=tools,
            events_config=events_config,
            planning=payload.planning,
            a2ui_enabled=payload.a2ui_enabled,
            agent_type=payload.agent_type,
        )
        agent = await self.create(agent)

        if payload.skill_ids:
            repo = self._get_agent_repository()
            await repo.set_skills(agent.id, [UUID(str(sid)) for sid in payload.skill_ids])

        await self.event_broker.publish(
            AgentCreated(
                agent_id=agent.id,
                name=agent.name,
                description=agent.description or "",
                model_id=agent.model_id or "",
                tools=agent.tools,
                events_config=agent.events_config,
                planning=agent.planning,
                a2ui_enabled=agent.a2ui_enabled,
            )
        )

        return agent

    async def _fork_catalog_agent(self, item: CatalogAgentItem) -> Agent:
        """Copy-on-write: materialize a tenant ``agents`` row from a catalog item.

        Creates a real, owned agent (workspace_id/created_by come from the
        repository's UserContext — never ``platform``), links it back to the
        catalog item via ``registry_item_id``, and records workspace-scoped
        install state for that catalog item.
        """
        spec = item.spec or {}
        tools = spec.get("tools")
        if not isinstance(tools, list):
            tools = None

        catalog_repo = self._get_catalog_repository()
        model_id = await catalog_repo.resolve_model_instance_id(_preferred_models_from_spec(spec))

        slug = await self._resolve_unique_slug(item.name)
        repo = self._get_agent_repository()
        agent = await repo.create(
            name=item.name,
            slug=slug,
            status="active",
            description=item.description
            if item.description is not None
            else spec.get("description"),
            instruction=spec.get("instruction"),
            model_id=model_id,
            tools=tools,
            events_config=spec.get("events_config"),
            planning=spec.get("planning"),
            registry_item_id=item.id,
        )
        await catalog_repo.mark_installed(item.id, str(agent.id), item.version)
        return agent

    async def install_catalog_agent(self, id: UUID) -> Agent | None:
        """Materialize a catalog agent into the workspace ("Add to workspace").

        Idempotent: if this workspace already forked the catalog item, the
        existing tenant copy is returned instead of creating a duplicate. Once
        forked, the catalog slug resolves to the tenant copy, so ``id`` may
        already be a real agent — that is treated as a no-op. Returns ``None``
        if ``id`` is neither a tenant agent nor a known catalog item.
        """
        existing = await self.get(id)
        if existing is not None:
            return existing
        item = await self._get_catalog_repository().get_item(str(id))
        if item is None:
            return None
        forked = await self._get_agent_repository().get_by_registry_item_id(item.id)
        if forked is not None:
            return forked
        return await self._fork_catalog_agent(item)

    @audited("agent.update", resource_type="agent", resource_id_param="id")
    async def update_agent(self, id: UUID, payload: AgentUpdate) -> Agent | None:
        agent = await self.get(id)
        if not agent:
            # The id may reference a catalog (not-yet-materialized) agent.
            # Editing one forks a real tenant copy (copy-on-write) and applies
            # the edit to that copy.
            item = await self._get_catalog_repository().get_item(str(id))
            if item is None:
                return None
            agent = await self._fork_catalog_agent(item)

        await self._check_write_access(agent)

        patch = payload.model_dump(exclude_unset=True)

        if "name" in patch:
            agent.name = patch["name"]
        if "capabilities" in patch:
            cast(Any, agent).capabilities = patch["capabilities"]
        if "description" in patch:
            agent.description = patch["description"]
        if "instruction" in patch:
            agent.instruction = patch["instruction"]
        if "model_id" in patch:
            agent.model_id = patch["model_id"]
        if "tools" in patch and payload.tools is not None:
            agent.tools = [t.model_dump(exclude_none=True) for t in payload.tools]
        if "events_config" in patch and payload.events_config is not None:
            agent.events_config = payload.events_config.model_dump()
        if "planning" in patch:
            agent.planning = patch["planning"]
        if "a2ui_enabled" in patch:
            agent.a2ui_enabled = patch["a2ui_enabled"]
        if "agent_type" in patch:
            agent.agent_type = patch["agent_type"]

        agent = await self.update(agent)

        if "skill_ids" in patch and payload.skill_ids is not None:
            repo = self._get_agent_repository()
            await repo.set_skills(agent.id, [UUID(str(sid)) for sid in payload.skill_ids])

        await self.event_broker.publish(
            AgentUpdated(
                agent_id=agent.id,
                name=agent.name,
                description=agent.description,
                model_id=agent.model_id,
                tools=agent.tools,
                events_config=agent.events_config,
                planning=agent.planning,
                a2ui_enabled=agent.a2ui_enabled,
            )
        )

        return agent

    async def get_by_name(self, name: str) -> Agent | None:
        """Get an agent by name."""
        repo = self._get_agent_repository()
        return await repo.get_agent_by_name(name)

    async def get_by_slug(self, slug: str) -> Agent | None:
        """Get an agent by workspace-scoped slug."""
        repo = self._get_agent_repository()
        return await repo.get_by_slug(slug)

    async def get_catalog_by_slug(self, slug: str) -> Agent | None:
        """Resolve a built-in catalog agent by its projected slug.

        Catalog agents are not materialized in the tenant ``agents`` table, so
        ``get_by_slug`` misses them. Their public slug is ``generate_slug(name)``
        (see :func:`_project_catalog_item`); match catalog items on that.
        """
        catalog_repo = self._get_catalog_repository()
        for item in await catalog_repo.list_items():
            if generate_slug(item.name) == slug:
                model_id = await catalog_repo.resolve_model_instance_id(
                    _preferred_models_from_spec(item.spec or {})
                )
                return _project_catalog_item(item, model_id)
        return None

    async def get_with_skills(self, id: UUID) -> Agent | None:
        """Get an agent with its skills loaded."""
        repo = self._get_agent_repository()
        return await repo.get_with_skills(id)

    @audited("agent.delete", resource_type="agent", resource_id_param="id")
    async def delete_agent(self, id: UUID) -> bool:
        agent = await self.get(id)
        if not agent:
            return False
        await self._check_write_access(agent)
        success = await self.delete(id)
        if success:
            await self.event_broker.publish(AgentDeleted(agent_id=id))
        return success
