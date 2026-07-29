"""Registry service — manages external registries and their catalog items.

Dispatches sync/create by registry_type:
  - "mcp_servers" → MCPServer specs
  - "skills" → Skill records
  - "llm_providers" → ProviderSpec
  - "llm_models" → ModelSpec (references provider by provider_key)
  - "agents" → catalog-only built-in agents (ADR-003): the registry_item IS
    the definition; no tenant `agents` row is materialized on sync.
  - "bundles" → catalog-only installable bundles: the registry_item.spec IS
    the canonical Bundle definition. Nothing is materialized on sync; the
    bundle is provisioned into a workspace on demand via BundleService.install.

Source format auto-detected (JSON or YAML).
Entity-specific details (connection_type, source_type) live in spec JSONB.
"""

import json
import logging
import urllib.request
from datetime import datetime
from typing import Any
from uuid import UUID

import yaml
from agentarea_common.utils.slug import generate_slug
from agentarea_mcp.infrastructure.repository import MCPServerRepository

from agentarea_registry.domain.models import Registry, RegistryItem
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)

logger = logging.getLogger(__name__)

VALID_REGISTRY_TYPES = (
    "mcp_servers",
    "skills",
    "llm_providers",
    "llm_models",
    "agents",
    "bundles",
)
VALID_SOURCE_TYPES = ("url", "github", "api")

# Top-level catalog key -> registry type. Each catalog document carries exactly
# one of these keys, so the registry type can be inferred from the payload shape
# when it is not stated explicitly.
TYPE_BY_TOPLEVEL_KEY = {
    "servers": "mcp_servers",
    "skills": "skills",
    "providers": "llm_providers",
    "models": "llm_models",
    "agents": "agents",
    "bundles": "bundles",
}


class RegistryService:
    """Manages registry CRUD, sync, and spec update operations."""

    def __init__(
        self,
        registry_repo: RegistryRepository,
        item_repo: RegistryItemRepository,
        server_repo: MCPServerRepository,
        skill_repo: Any | None = None,
        provider_spec_repo: Any | None = None,
        model_spec_repo: Any | None = None,
        agent_repo: Any | None = None,
    ):
        self.registry_repo = registry_repo
        self.item_repo = item_repo
        self.server_repo = server_repo
        self.skill_repo = skill_repo
        self.provider_spec_repo = provider_spec_repo
        self.model_spec_repo = model_spec_repo
        self.agent_repo = agent_repo

    # ── Registry CRUD ──

    async def create_registry(
        self,
        name: str,
        registry_type: str,
        source_type: str,
        source_url: str,
        description: str | None = None,
        sync_mode: str = "manual",
    ) -> Registry:
        if registry_type not in VALID_REGISTRY_TYPES:
            raise ValueError(f"registry_type must be one of {VALID_REGISTRY_TYPES}")
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {VALID_SOURCE_TYPES}")
        return await self.registry_repo.create(
            name=name,
            registry_type=registry_type,
            source_type=source_type,
            source_url=source_url,
            description=description,
            sync_mode=sync_mode,
        )

    async def get_registry(self, registry_id: UUID) -> Registry | None:
        return await self.registry_repo.get_by_id(registry_id)

    async def list_registries(
        self, active_only: bool = False, registry_type: str | None = None
    ) -> list[Registry]:
        if active_only:
            return await self.registry_repo.list_active(registry_type=registry_type)
        if registry_type:
            return await self.registry_repo.list_all(registry_type=registry_type)
        return await self.registry_repo.list_all()

    async def update_registry(self, registry_id: UUID, **fields) -> Registry | None:
        return await self.registry_repo.update(registry_id, **fields)

    async def delete_registry(self, registry_id: UUID) -> bool:
        return await self.registry_repo.delete(registry_id)

    # ── Catalog browsing ──

    async def list_items(
        self, registry_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[RegistryItem]:
        return await self.item_repo.list_by_registry(registry_id, limit=limit, offset=offset)

    async def search_catalog(
        self,
        query: str | None = None,
        tag: str | None = None,
        update_available: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RegistryItem]:
        return await self.item_repo.search(
            query_str=query,
            tag=tag,
            update_available=update_available,
            limit=limit,
            offset=offset,
        )

    async def get_item(self, item_id: UUID) -> RegistryItem | None:
        return await self.item_repo.get_by_id(item_id)

    # ── Sync ──

    async def sync_registry(self, registry_id: UUID) -> dict[str, Any]:
        """Sync: fetch source, upsert catalog, auto-create entities for new items."""
        registry = await self.registry_repo.get_by_id(registry_id)
        if not registry:
            raise ValueError(f"Registry {registry_id} not found")

        try:
            raw_data = self._fetch_source(registry.source_url)
            parsed_items = self._parse_source(registry.registry_type, raw_data)

            new_specs = 0
            updates_flagged = 0
            unchanged = 0

            for item_data in parsed_items:
                existing = await self.item_repo.get_by_external_id(
                    registry_id=registry_id,
                    external_id=item_data["external_id"],
                )

                if existing:
                    for field in ("name", "description", "spec", "tags"):
                        if field in item_data:
                            setattr(existing, field, item_data[field])

                    new_version = item_data.get("version") or "latest"
                    existing.version = new_version

                    if existing.installed_version and existing.installed_version != new_version:
                        existing.update_available = True
                        updates_flagged += 1
                    else:
                        unchanged += 1

                    await self.item_repo.session.commit()
                    await self.item_repo.session.refresh(existing)

                    # Backfill json_spec on linked entity if missing
                    if existing.installed_entity_id:
                        raw_spec = (existing.spec or {}).get("raw_spec")
                        if raw_spec:
                            await self._backfill_entity(
                                registry.registry_type, existing, registry_url=registry.source_url
                            )
                else:
                    item = await self.item_repo.create(
                        registry_id=registry_id,
                        external_id=item_data["external_id"],
                        name=item_data["name"],
                        description=item_data.get("description"),
                        version=item_data.get("version"),
                        spec=item_data.get("spec", {}),
                        tags=item_data.get("tags", []),
                    )
                    entity_id = await self._create_entity(
                        registry.registry_type, item, registry_url=registry.source_url
                    )
                    await self.item_repo.update(
                        item.id,
                        installed_entity_id=entity_id,
                        installed_version=item.version or "latest",
                    )
                    new_specs += 1

            total = new_specs + updates_flagged + unchanged
            await self.registry_repo.update(
                registry_id,
                last_synced_at=datetime.utcnow(),
                last_sync_error=None,
                item_count=total,
            )

            return {
                "new_specs": new_specs,
                "updates_flagged": updates_flagged,
                "unchanged": unchanged,
                "total": len(parsed_items),
            }

        except Exception as e:
            logger.exception(f"Registry sync failed for {registry_id}")
            await self.registry_repo.update(registry_id, last_sync_error=str(e))
            raise

    # ── Update specs ──

    async def update_item_spec(self, item_id: UUID) -> Any:
        """Apply the registry version to the installed entity."""
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            raise ValueError(f"Registry item {item_id} not found")
        if not item.installed_entity_id:
            raise ValueError(f"Item {item.name} has no installed entity")
        if not item.update_available:
            raise ValueError(f"Item {item.name} is already up to date")

        registry = await self.registry_repo.get_by_id(item.registry_id)
        if not registry:
            raise ValueError(f"Registry {item.registry_id} not found")

        entity = await self._update_entity(
            registry.registry_type, item, registry_url=registry.source_url
        )
        await self.item_repo.update(
            item_id,
            update_available=False,
            installed_version=item.version or "latest",
        )
        return entity

    async def update_all_specs(self, registry_id: UUID) -> dict[str, int]:
        """Bulk-update all items with update_available=True."""
        items = await self.item_repo.list_by_registry(registry_id)
        updated = 0
        errors = 0
        for item in items:
            if not item.update_available:
                continue
            try:
                await self.update_item_spec(item.id)
                updated += 1
            except Exception as e:
                logger.warning(f"Failed to update {item.name}: {e}")
                errors += 1
        return {"updated": updated, "errors": errors}

    # ── Entity dispatchers ──

    async def _create_entity(
        self, registry_type: str, item: RegistryItem, registry_url: str | None = None
    ) -> str | None:
        if registry_type == "mcp_servers":
            return await self._create_mcp_server(item, registry_url=registry_url)
        elif registry_type == "skills":
            return await self._create_skill(item)
        elif registry_type == "llm_providers":
            return await self._create_llm_provider(item)
        elif registry_type == "llm_models":
            return await self._create_llm_model(item)
        elif registry_type == "agents":
            # Catalog-only (ADR-003): the registry_item is the built-in agent
            # definition; no tenant `agents` row is materialized on sync. A real
            # row is created copy-on-write when a user edits the catalog agent.
            return None
        elif registry_type == "bundles":
            # Catalog-only: the registry_item.spec is the canonical Bundle. It is
            # provisioned into a workspace on demand via BundleService.install, so
            # nothing is materialized on sync.
            return None
        raise ValueError(f"Unknown registry_type: {registry_type}")

    async def _update_entity(
        self, registry_type: str, item: RegistryItem, registry_url: str | None = None
    ) -> Any:
        if registry_type == "mcp_servers":
            return await self._update_mcp_server(item, registry_url=registry_url)
        elif registry_type == "skills":
            return await self._update_skill(item)
        elif registry_type == "llm_providers":
            return await self._update_llm_provider(item)
        elif registry_type == "llm_models":
            return await self._update_llm_model(item)
        elif registry_type == "agents":
            # No materialized entity to update for catalog agents (ADR-003).
            return None
        elif registry_type == "bundles":
            # No materialized entity to update for catalog bundles.
            return None
        raise ValueError(f"Unknown registry_type: {registry_type}")

    # ── MCP Server handlers ──

    async def _resolve_unique_slug(self, repo: Any, name: str) -> str:
        """Workspace-scoped unique slug, using ``repo.get_by_slug`` for collision checks."""
        base = generate_slug(name)
        if await repo.get_by_slug(base) is None:
            return base
        for suffix in range(2, 1000):
            candidate = f"{base}-{suffix}"
            if await repo.get_by_slug(candidate) is None:
                return candidate
        raise ValueError(f"Exhausted collision suffixes (-2..-999) for slug base '{base}'")

    async def _create_mcp_server(self, item: RegistryItem, registry_url: str | None = None) -> str:
        spec = item.spec or {}
        conn_type = spec.get("connection_type", "url")
        docker_image_url, cmd = self._map_mcp_connection(conn_type, spec)
        remote_url = spec.get("url") if conn_type == "url" else None
        raw_spec = spec.get("raw_spec")
        tags = ["registry", conn_type]
        if spec.get("transport"):
            tags.append(spec["transport"])

        slug = await self._resolve_unique_slug(self.server_repo, item.name)

        server = await self.server_repo.create(
            name=item.name,
            slug=slug,
            description=item.description or "",
            docker_image_url=docker_image_url,
            version=item.version or "latest",
            tags=tags,
            is_public=False,
            env_schema=spec.get("env_schema", []),
            cmd=cmd,
            remote_url=remote_url,
            registry_item_id=item.id,
            json_spec=raw_spec,
            registry_url=registry_url,
        )
        return str(server.id)

    async def _update_mcp_server(self, item: RegistryItem, registry_url: str | None = None) -> Any:
        spec = item.spec or {}
        conn_type = spec.get("connection_type", "url")
        docker_image_url, cmd = self._map_mcp_connection(conn_type, spec)
        remote_url = spec.get("url") if conn_type == "url" else None
        raw_spec = spec.get("raw_spec")
        tags = ["registry", conn_type]
        if spec.get("transport"):
            tags.append(spec["transport"])

        if item.installed_entity_id is None:
            raise ValueError(f"Registry item {item.id} is not installed")

        return await self.server_repo.update(
            item.installed_entity_id,
            description=item.description or "",
            docker_image_url=docker_image_url,
            version=item.version or "latest",
            tags=tags,
            env_schema=spec.get("env_schema", []),
            cmd=cmd,
            remote_url=remote_url,
            json_spec=raw_spec,
            registry_url=registry_url,
        )

    async def _backfill_entity(
        self, registry_type: str, item: RegistryItem, registry_url: str | None = None
    ):
        """Update entity with json_spec/remote_url if missing."""
        if registry_type != "mcp_servers":
            return
        spec = item.spec or {}
        raw_spec = spec.get("raw_spec")
        if not raw_spec or not item.installed_entity_id:
            return
        conn_type = spec.get("connection_type", "url")
        remote_url = spec.get("url") if conn_type == "url" else None
        try:
            await self.server_repo.update(
                item.installed_entity_id,
                json_spec=raw_spec,
                remote_url=remote_url,
                registry_url=registry_url,
                env_schema=spec.get("env_schema", []),
            )
        except Exception:
            logger.debug("Backfill failed for %s", item.installed_entity_id, exc_info=True)

    @staticmethod
    def _map_mcp_connection(conn_type: str, spec: dict) -> tuple[str, list[str] | None]:
        docker_image_url = ""
        cmd = None
        if conn_type == "docker":
            docker_image_url = spec.get("image", "")
        elif conn_type == "command":
            docker_image_url = "agentarea/mcp-bridge:latest"
            command = spec.get("command", "")
            args = spec.get("args", [])
            cmd = [command, *args] if command else None
        return docker_image_url, cmd

    # ── Skill handlers ──

    async def _create_skill(self, item: RegistryItem) -> str:
        if not self.skill_repo:
            raise ValueError("Skill repository not available")
        spec = item.spec or {}
        slug = await self._resolve_unique_slug(self.skill_repo, item.name)
        skill = await self.skill_repo.create(
            name=item.name,
            slug=slug,
            description=item.description,
            source_type=spec.get("source_type", "content"),
            content=spec.get("content"),
            source_url=spec.get("source_url"),
            registry_item_id=item.id,
        )
        return str(skill.id)

    async def _update_skill(self, item: RegistryItem) -> Any:
        if not self.skill_repo:
            raise ValueError("Skill repository not available")
        spec = item.spec or {}
        return await self.skill_repo.update(
            item.installed_entity_id,
            description=item.description,
            content=spec.get("content"),
            source_url=spec.get("source_url"),
        )

    # ── LLM provider handlers ──

    async def _create_llm_provider(self, item: RegistryItem) -> str:
        if not self.provider_spec_repo:
            raise ValueError("Provider spec repository not available")
        from agentarea_llm.domain.models import ProviderSpec

        spec = item.spec or {}
        entity = ProviderSpec(
            provider_key=spec["provider_key"],
            name=item.name,
            description=item.description,
            provider_type=spec.get("provider_type", spec["provider_key"]),
            icon=spec.get("icon"),
            is_builtin=spec.get("is_builtin", True),
        )
        created = await self.provider_spec_repo.upsert_by_provider_key(entity)
        return str(created.id)

    async def _update_llm_provider(self, item: RegistryItem) -> Any:
        if not self.provider_spec_repo:
            raise ValueError("Provider spec repository not available")
        from agentarea_llm.domain.models import ProviderSpec

        spec = item.spec or {}
        entity = ProviderSpec(
            provider_key=spec["provider_key"],
            name=item.name,
            description=item.description,
            provider_type=spec.get("provider_type", spec["provider_key"]),
            icon=spec.get("icon"),
            is_builtin=spec.get("is_builtin", True),
        )
        return await self.provider_spec_repo.upsert_by_provider_key(entity)

    # ── LLM model handlers ──

    async def _create_llm_model(self, item: RegistryItem) -> str:
        if not (self.model_spec_repo and self.provider_spec_repo):
            raise ValueError("Provider and model spec repositories required")
        spec = item.spec or {}
        provider = await self.provider_spec_repo.get_by_provider_key(spec["provider_key"])
        if not provider:
            raise ValueError(
                f"Provider '{spec['provider_key']}' not found; sync llm_providers registry first"
            )
        model = await self.model_spec_repo.upsert_by_provider_and_model_kwargs(
            provider_spec_id=provider.id,
            model_name=spec["model_name"],
            display_name=item.name,
            description=item.description,
            context_window=spec.get("context_window", 4096),
            max_output_tokens=spec.get("max_output_tokens"),
            input_cost_per_token=spec.get("input_cost_per_token"),
            output_cost_per_token=spec.get("output_cost_per_token"),
            supports_function_calling=spec.get("supports_function_calling", False),
            is_active=spec.get("is_active", True),
        )
        return str(model.id)

    async def _update_llm_model(self, item: RegistryItem) -> Any:
        return await self._create_llm_model(item)

    # ── Source fetching (format-agnostic) ──

    @staticmethod
    def _fetch_source(source_url: str) -> dict[str, Any]:
        """Fetch data from URL, auto-detect JSON vs YAML."""
        if source_url.startswith("http://") or source_url.startswith("https://"):
            req = urllib.request.Request(  # noqa: S310
                source_url,
                headers={
                    "Accept": "application/json, application/yaml, text/yaml, */*",
                    "User-Agent": "agentarea-registry-sync",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
                content_type = resp.headers.get("Content-Type", "")
        else:
            with open(source_url) as f:
                raw = f.read()
            content_type = ""

        if "yaml" in content_type or source_url.endswith((".yaml", ".yml")):
            return yaml.safe_load(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return yaml.safe_load(raw)

    @staticmethod
    def _detect_type(data: Any) -> str:
        """Infer the registry type from a fetched catalog's top-level key."""
        if not isinstance(data, dict):
            raise ValueError("cannot detect registry type: source root is not a mapping")
        matched = [
            rtype for key, rtype in TYPE_BY_TOPLEVEL_KEY.items() if isinstance(data.get(key), list)
        ]
        if len(matched) == 1:
            return matched[0]
        if not matched:
            raise ValueError(
                "cannot detect registry type: expected one top-level key of "
                f"{list(TYPE_BY_TOPLEVEL_KEY)}"
            )
        raise ValueError(f"ambiguous registry type: multiple catalog keys present {matched}")

    @classmethod
    def detect_type_from_source(cls, source_url: str) -> str:
        """Fetch a source and infer its registry type from the payload shape."""
        return cls._detect_type(cls._fetch_source(source_url))

    # ── Source parsing (type-dispatched) ──

    @staticmethod
    def _parse_source(registry_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        if registry_type == "mcp_servers":
            return RegistryService._parse_mcp_servers(data)
        elif registry_type == "skills":
            return RegistryService._parse_skills(data)
        elif registry_type == "llm_providers":
            return RegistryService._parse_llm_providers(data)
        elif registry_type == "llm_models":
            return RegistryService._parse_llm_models(data)
        elif registry_type == "agents":
            return RegistryService._parse_agents(data)
        elif registry_type == "bundles":
            return RegistryService._parse_bundles(data)
        raise ValueError(f"Unknown registry_type: {registry_type}")

    @staticmethod
    def _parse_mcp_servers(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse MCP servers from the standard registry format.

        Standard format (registry.modelcontextprotocol.io):
            {"servers": [{"server": {"name": ..., "remotes": [...], "packages": [...]}, "_meta": {...}}]}
        """
        servers = data.get("servers", [])
        if not servers:
            return []

        first = servers[0]
        if "server" not in first:
            raise ValueError(
                "Unrecognized MCP registry format: each entry of 'servers' must contain a "
                f"'server' key (got keys: {sorted(first)})"
            )
        return RegistryService._parse_standard_mcp_registry(servers)

    @staticmethod
    def _parse_standard_mcp_registry(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parse official MCP registry format (remotes + packages)."""
        items = []
        for entry in servers:
            server = entry.get("server", {})
            meta = entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})

            # Only import latest versions
            if not meta.get("isLatest", True):
                continue

            identifier = server.get("name", "")
            if not identifier:
                continue

            title = server.get("title") or _humanize_identifier(identifier)
            description = (server.get("description") or "")[:500]
            version = server.get("version", "latest")

            # Remote endpoints → connection_type: "url"
            for remote in server.get("remotes", []):
                transport = remote.get("type", "streamable-http")
                url = remote.get("url", "")
                if not url:
                    continue

                # Store headers as-is (raw KeyValueInput format from registry)
                raw_headers = remote.get("headers", [])
                env_schema: list[dict[str, Any]] = []
                if isinstance(raw_headers, list):
                    env_schema = [h for h in raw_headers if isinstance(h, dict)]

                requires_auth = any(
                    h.get("name", "").lower() in ("authorization", "api_key", "x-api-key", "token")
                    for h in env_schema
                )

                tags = [transport]
                if requires_auth:
                    tags.append("requires-auth")

                items.append(
                    {
                        "external_id": identifier,
                        "name": title,
                        "description": description,
                        "version": version,
                        "spec": {
                            "connection_type": "url",
                            "url": url,
                            "transport": transport,
                            "env_schema": env_schema,
                            "raw_spec": server,
                        },
                        "tags": tags,
                    }
                )

            # OCI packages → connection_type: "docker"
            for pkg in server.get("packages", []):
                if pkg.get("registryType") != "oci":
                    continue
                image = pkg.get("name", "") or pkg.get("identifier", "")
                pkg_version = pkg.get("version", version)
                if not image:
                    continue

                # Store raw KeyValueInput as-is from registry
                env_schema = [
                    ev for ev in pkg.get("environmentVariables", []) if isinstance(ev, dict)
                ]

                items.append(
                    {
                        "external_id": f"{identifier}/docker",
                        "name": title,
                        "description": description,
                        "version": pkg_version,
                        "spec": {
                            "connection_type": "docker",
                            "image": f"{image}:{pkg_version}" if ":" not in image else image,
                            "transport": "stdio",
                            "env_schema": env_schema,
                            "raw_spec": server,
                        },
                        "tags": ["docker", "oci"],
                    }
                )

            # npm/pypi/nuget/mcpb packages → connection_type: "command"
            for pkg in server.get("packages", []):
                reg_type = pkg.get("registryType", "")
                if reg_type not in ("npm", "pypi", "nuget", "mcpb"):
                    continue
                pkg_name = pkg.get("name", "") or pkg.get("identifier", "")
                pkg_version = pkg.get("version", version)
                if not pkg_name:
                    continue

                runtime_args = pkg.get("runtimeArgs", [])
                if runtime_args:
                    command = runtime_args[0]
                    args = runtime_args[1:]
                elif reg_type == "npm":
                    command = "npx"
                    args = ["-y", pkg_name]
                elif reg_type == "nuget":
                    command = "dotnet"
                    args = ["tool", "run", pkg_name]
                elif reg_type == "mcpb":
                    command = "npx"
                    args = ["-y", pkg_name]
                else:
                    command = "uvx"
                    args = [pkg_name]

                # Store raw KeyValueInput as-is from registry
                env_schema = [
                    ev for ev in pkg.get("environmentVariables", []) if isinstance(ev, dict)
                ]

                items.append(
                    {
                        "external_id": f"{identifier}/command",
                        "name": title,
                        "description": description,
                        "version": pkg_version,
                        "spec": {
                            "connection_type": "command",
                            "command": command,
                            "args": args,
                            "transport": "stdio",
                            "package_registry": reg_type,
                            "package_name": pkg_name,
                            "env_schema": env_schema,
                            "raw_spec": server,
                        },
                        "tags": ["command", reg_type],
                    }
                )

        return items

    @staticmethod
    def _parse_skills(data: dict[str, Any]) -> list[dict[str, Any]]:
        skills = data.get("skills", [])
        items = []
        for entry in skills:
            name = entry.get("name", "")
            if not name:
                continue
            items.append(
                {
                    "external_id": name,
                    "name": name,
                    "description": entry.get("description"),
                    "version": entry.get("version") or "1.0.0",
                    "spec": {
                        "source_type": entry.get("source_type", "content"),
                        "content": entry.get("content"),
                        "source_url": entry.get("source_url"),
                    },
                    "tags": entry.get("tags", []),
                }
            )
        return items

    @staticmethod
    def _parse_llm_providers(data: dict[str, Any]) -> list[dict[str, Any]]:
        providers = data.get("providers", [])
        items = []
        for entry in providers:
            provider_key = entry.get("provider_key")
            if not provider_key:
                continue
            items.append(
                {
                    "external_id": provider_key,
                    "name": entry.get("name") or provider_key,
                    "description": entry.get("description"),
                    "version": entry.get("version") or "1.0.0",
                    "spec": {
                        "provider_key": provider_key,
                        "provider_type": entry.get("provider_type", provider_key),
                        "icon": entry.get("icon"),
                        "is_builtin": entry.get("is_builtin", True),
                    },
                    "tags": entry.get("tags", []),
                }
            )
        return items

    @staticmethod
    def _parse_llm_models(data: dict[str, Any]) -> list[dict[str, Any]]:
        models = data.get("models", [])
        items = []
        for entry in models:
            provider_key = entry.get("provider_key")
            model_name = entry.get("model_name")
            if not provider_key or not model_name:
                continue
            items.append(
                {
                    "external_id": f"{provider_key}/{model_name}",
                    "name": entry.get("display_name") or model_name,
                    "description": entry.get("description"),
                    "version": entry.get("version") or "1.0.0",
                    "spec": {
                        "provider_key": provider_key,
                        "model_name": model_name,
                        "context_window": entry.get("context_window", 4096),
                        "max_output_tokens": entry.get("max_output_tokens"),
                        "input_cost_per_token": entry.get("input_cost_per_token"),
                        "output_cost_per_token": entry.get("output_cost_per_token"),
                        "supports_function_calling": entry.get("supports_function_calling", False),
                        "is_active": entry.get("is_active", True),
                    },
                    "tags": entry.get("tags", []),
                }
            )
        return items

    @staticmethod
    def _parse_agents(data: dict[str, Any]) -> list[dict[str, Any]]:
        agents = data.get("agents", [])
        items = []
        for entry in agents:
            name = entry.get("name")
            if not name:
                continue
            agent_id = entry.get("id")
            tools = entry.get("tools") or []
            if not isinstance(tools, list):
                tools = []
            items.append(
                {
                    "external_id": str(agent_id) if agent_id else name,
                    "name": name,
                    "description": entry.get("description"),
                    "version": entry.get("version") or "1.0.0",
                    "spec": {
                        "id": agent_id,
                        "name": name,
                        "description": entry.get("description"),
                        "instruction": entry.get("instruction", ""),
                        # Catalog is global; model instances are per-workspace. Carry
                        # model *preferences* (slugs, priority order) — never a concrete
                        # ``model_id`` (instance UUID), which is resolved per workspace
                        # at install time.
                        "preferred_models": _agent_preferred_models(entry),
                        "tools": tools,
                        "planning": entry.get("planning", False),
                        "events_config": entry.get("events_config"),
                    },
                    "tags": entry.get("tags", []),
                }
            )
        return items

    @staticmethod
    def _parse_bundles(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse installable bundles.

        Each catalog entry IS a canonical Bundle (the same shape the
        ``/v1/bundles/install`` endpoint consumes). The whole entry is stored as
        the registry_item ``spec`` so install can run against it unchanged;
        ``external_id`` is the bundle ``name`` (its idempotency key).
        """
        items = []
        for entry in data.get("bundles", []):
            name = entry.get("name")
            if not name:
                continue
            metadata = entry.get("metadata") or {}
            tags = entry.get("tags") or metadata.get("capabilities") or []
            if not isinstance(tags, list):
                tags = []
            items.append(
                {
                    "external_id": name,
                    "name": entry.get("display_name") or name,
                    "description": entry.get("description"),
                    "version": entry.get("schema_version") or entry.get("version") or "0.1.0",
                    "spec": entry,
                    "tags": tags,
                }
            )
        return items


def _agent_preferred_models(entry: dict[str, Any]) -> list[str]:
    """Extract a catalog agent's preferred model slugs in priority order."""
    preferred = entry.get("preferred_models")
    if isinstance(preferred, list):
        return [m for m in preferred if isinstance(m, str) and m]
    return []


def _humanize_identifier(identifier: str) -> str:
    """Convert registry identifier to a human-readable name.

    Examples:
        'ai.aliengiraffe/spotdb'     → 'Spotdb'
        'com.github/copilot-mcp'     → 'Copilot MCP'
        'agency.lona/trading'        → 'Trading'
    """
    # Take the part after the last slash
    if "/" in identifier:
        name = identifier.rsplit("/", 1)[-1]
    else:
        name = identifier

    # Known abbreviations to keep uppercase
    abbrevs = {"mcp", "api", "ai", "db", "sql", "ssh", "aws", "gcp", "cli", "sdk", "llm"}

    parts = name.replace("-", " ").replace("_", " ").split()
    return " ".join(p.upper() if p.lower() in abbrevs else p.capitalize() for p in parts)
