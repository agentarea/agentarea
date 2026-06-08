# libs/common/agentarea_common/reconciler/service.py
"""IaC config reconciler: YAML -> DB for system entities.

Additive-only — creates and updates but never deletes.
Uses raw async SQLAlchemy (not workspace-scoped repos) because:
1. Consistent with existing bootstrap scripts.
2. Workspace-scoped repos filter OUT system entities.
3. This is a trusted internal process.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentarea_common.base.source import SourceKind
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID, PLATFORM_WORKSPACE_ID

from .parsers import YAMLValidationError, parse_yaml

logger = logging.getLogger(__name__)

SYSTEM_WORKSPACE_ID = PLATFORM_WORKSPACE_ID
SYSTEM_USER_ID = PLATFORM_PRINCIPAL_ID


@dataclass
class ReconcileResult:
    """Tracks reconciliation outcomes."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def add_error(self, entity_type: str, message: str) -> None:
        self.errors.append((entity_type, message))

    def __str__(self) -> str:
        """Return human-readable representation."""
        error_count = len(self.errors)
        return (
            f"ReconcileResult(created={self.created}, updated={self.updated}, "
            f"skipped={self.skipped}, errors={error_count})"
        )


class ReconcilerService:
    """Additive-only config applier: YAML -> DB for system entities."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def reconcile(self, config_dir: str) -> ReconcileResult:
        """Read all YAML files from config_dir and upsert into DB."""
        result = ReconcileResult()
        config_path = Path(config_dir)

        for entity_type in ["mcp_servers", "agents", "skills", "models"]:
            yaml_file = config_path / f"{entity_type}.yaml"
            if not yaml_file.exists():
                logger.debug("No %s.yaml found in %s, skipping", entity_type, config_dir)
                continue

            # Built-in skills live in the registry catalog only (ADR-003): they
            # are not materialized into the `skills` table. A real tenant row is
            # created copy-on-write when a user edits a catalog skill.
            if entity_type == "skills":
                logger.debug(
                    "Skipping skills.yaml reconcile: built-in skills are catalog-only (ADR-003)"
                )
                continue

            try:
                specs = parse_yaml(yaml_file, entity_type)
            except YAMLValidationError as e:
                logger.error("Invalid YAML in %s: %s", yaml_file, e)
                result.add_error(entity_type, str(e))
                continue

            logger.info("Reconciling %d %s from %s", len(specs), entity_type, yaml_file)
            await self._upsert_entities(entity_type, specs, result)

        logger.info("Reconciliation complete: %s", result)
        return result

    async def _upsert_entities(
        self,
        entity_type: str,
        specs: list[dict],
        result: ReconcileResult,
    ) -> None:
        """Upsert entities with workspace_id='system'."""
        model_class = self._get_model_class(entity_type)
        if model_class is None:
            result.add_error(entity_type, f"Unknown entity type: {entity_type}")
            return

        async with self._session_factory() as session:
            for spec in specs:
                name = spec.get("name")
                try:
                    existing = await session.execute(
                        select(model_class).where(
                            model_class.name == name,
                            model_class.workspace_id == SYSTEM_WORKSPACE_ID,
                        )
                    )
                    entity = existing.scalar_one_or_none()

                    if entity:
                        self._apply_updates(entity, spec)
                        result.updated += 1
                        logger.debug("Updated %s: %s", entity_type, name)
                    else:
                        entity = model_class(
                            id=uuid4(),
                            workspace_id=SYSTEM_WORKSPACE_ID,
                            created_by=SYSTEM_USER_ID,
                            **self._prepare_create_fields(spec, entity_type),
                        )
                        session.add(entity)
                        result.created += 1
                        logger.debug("Created %s: %s", entity_type, name)

                    # Platform-seeded entities are built-in (provenance), so
                    # is_builtin() holds regardless of seeding path. Only the
                    # source-bearing tables (agents, skills) carry the column.
                    if hasattr(entity, "source"):
                        entity.source = SourceKind.OFFICIAL

                    await session.commit()
                except Exception as e:
                    await session.rollback()
                    logger.error("Failed to upsert %s '%s': %s", entity_type, name, e)
                    result.add_error(entity_type, f"{name}: {e}")

    def _get_model_class(self, entity_type: str):
        """Lazy-import model classes to avoid circular imports."""
        if entity_type == "mcp_servers":
            from agentarea_mcp.domain.models import MCPServer

            return MCPServer
        elif entity_type == "agents":
            from agentarea_agents.domain.models import Agent

            return Agent
        elif entity_type == "skills":
            from agentarea_agents.domain.skill_models import Skill

            return Skill
        elif entity_type == "models":
            # Models have nested structure (providers + instances).
            # Handle via dedicated _reconcile_models() method.
            return None  # Special-cased in reconcile()
        return None

    def _prepare_create_fields(self, spec: dict, entity_type: str) -> dict:
        """Prepare fields for entity creation, handling JSON serialization."""
        fields = dict(spec)
        # JSON-serialize complex fields
        if entity_type == "mcp_servers":
            for json_field in ["env_schema", "cmd", "tags"]:
                if json_field in fields and not isinstance(fields[json_field], str):
                    fields[json_field] = json.dumps(fields[json_field])
        elif entity_type == "agents":
            if "tools" in fields and not isinstance(fields["tools"], str):
                fields["tools"] = json.dumps(fields["tools"])
            # Remove fields that need separate handling
            fields.pop("skills", None)
        return fields

    def _apply_updates(self, entity, spec: dict) -> None:
        """Apply spec fields to existing entity."""
        skip_fields = {"name", "skills"}  # name is the lookup key, skills are M2M
        for key, value in spec.items():
            if key in skip_fields:
                continue
            if hasattr(entity, key):
                if isinstance(value, dict | list):
                    value = json.dumps(value)
                setattr(entity, key, value)
