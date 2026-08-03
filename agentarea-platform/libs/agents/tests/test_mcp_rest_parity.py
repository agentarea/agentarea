"""Contract test: MCP toolset method kwargs must align with REST body Pydantic models.

This catches drift the moment a developer adds a new field to a REST DTO
(e.g. ``AgentCreate``) but forgets to expose it as a kwarg on the
corresponding MCP tool method (e.g. ``AgentsToolset.create``), or vice versa.

The test is parity-by-subset: every toolset kwarg must either
- exist as a field on the linked Pydantic DTO, or
- be a path-like identifier (``project_id``, ``config_id``, ...), or
- carry the ``_json`` suffix and map to a JSON-typed DTO field of the
  same root name (LLM-friendly: nested objects passed as JSON strings).

Toolsets are allowed to expose **fewer** kwargs than the DTO has fields —
some REST fields are too complex for LLM tools to set, or are managed via
dedicated tools. Those omissions must be declared in ``UNCOVERED_FIELDS`` so
the gap is explicit and code-reviewable.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import NamedTuple

import pytest
from pydantic import BaseModel

from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_agents.schemas.skills_dto import (
    SkillCreateFromArchive,
    SkillCreateFromFiles,
    SkillEditContent,
    SkillEditMetadata,
    SkillImportFromGithub,
)
from agentarea_api.tools.agents_toolset import AgentsToolset
from agentarea_api.tools.mcp_servers_toolset import MCPServersToolset
from agentarea_api.tools.openapi_connections_toolset import OpenAPIConnectionsToolset
from agentarea_api.tools.projects_toolset import ProjectsToolset
from agentarea_api.tools.providers_toolset import ProvidersToolset
from agentarea_api.tools.runs_toolset import RunsToolset
from agentarea_api.tools.skills_toolset import SkillsToolset
from agentarea_api.tools.triggers_toolset import TriggersToolset
from agentarea_llm.schemas.dto import ProviderConfigCreate, ProviderConfigUpdate
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
    MCPServerInstanceUpdate,
    MCPServerUpdate,
)
from agentarea_openapi.schemas.dto import (
    OpenAPIConnectionCreate,
    OpenAPIConnectionUpdate,
)
from agentarea_projects.schemas.dto import ProjectCreate, ProjectUpdate
from agentarea_tasks.schemas.dto import RunCreate
from agentarea_triggers.schemas.dto import TriggerCreate


class Pair(NamedTuple):
    label: str
    method: Callable
    model: type[BaseModel]


# Each entry pairs an MCP toolset method to its REST/DTO Pydantic model.
# When you add a new toolset CRUD method, register it here.
PAIRS: list[Pair] = [
    Pair("agents.create", AgentsToolset.create, AgentCreate),
    Pair("agents.update", AgentsToolset.update, AgentUpdate),
    Pair("runs.start", RunsToolset.start, RunCreate),
    Pair("projects.create", ProjectsToolset.create, ProjectCreate),
    Pair("projects.update", ProjectsToolset.update, ProjectUpdate),
    Pair("providers.create_config", ProvidersToolset.create_config, ProviderConfigCreate),
    Pair("providers.update_config", ProvidersToolset.update_config, ProviderConfigUpdate),
    Pair(
        "openapi_connections.create",
        OpenAPIConnectionsToolset.create,
        OpenAPIConnectionCreate,
    ),
    Pair(
        "openapi_connections.update",
        OpenAPIConnectionsToolset.update,
        OpenAPIConnectionUpdate,
    ),
    Pair("mcp_servers.create_spec", MCPServersToolset.create_spec, MCPServerCreate),
    Pair("mcp_servers.update_spec", MCPServersToolset.update_spec, MCPServerUpdate),
    Pair("mcp_servers.create", MCPServersToolset.create, MCPServerInstanceCreate),
    Pair("mcp_servers.update", MCPServersToolset.update, MCPServerInstanceUpdate),
    Pair("skills.create", SkillsToolset.create, SkillCreateFromFiles),
    Pair(
        "skills.create_from_archive",
        SkillsToolset.create_from_archive,
        SkillCreateFromArchive,
    ),
    Pair(
        "skills.import_from_github",
        SkillsToolset.import_from_github,
        SkillImportFromGithub,
    ),
    Pair("skills.edit_metadata", SkillsToolset.edit_metadata, SkillEditMetadata),
    Pair("skills.edit_content", SkillsToolset.edit_content, SkillEditContent),
    Pair("triggers.create_cron", TriggersToolset.create_cron, TriggerCreate),
    Pair("triggers.create_webhook", TriggersToolset.create_webhook, TriggerCreate),
]

# DTO fields intentionally NOT exposed as toolset kwargs. Per-pair so omissions
# are explicit. Three categories:
#   1. Complex/nested fields that don't translate to flat MCP kwargs (e.g. ``tools``).
#   2. Fields managed via dedicated tools (e.g. ``skill_ids`` via add/remove).
#   3. Fields fixed by the method (e.g. ``trigger_type`` is hardcoded to "cron"
#      inside ``create_cron``, so the user never sets it).
UNCOVERED_FIELDS: dict[str, set[str]] = {
    "agents.create": {
        "tools",
        "events_config",
        "planning",
        "a2ui_enabled",
        "skill_ids",
    },
    "agents.update": {
        "tools",
        "events_config",
        "planning",
        "a2ui_enabled",
        "skill_ids",
        "capabilities",
        "agent_type",
    },
    # ``task_policy`` is a governance-set field (budget/policy snapshot applied by
    # the caller/PEP), not an agent-facing kwarg — agents don't set their own policy.
    # The typed execution object is represented by the tool's flat max_iterations
    # argument and translated by the service.
    "runs.start": {"task_policy", "execution"},
    "projects.create": set(),
    "projects.update": set(),
    "providers.create_config": set(),
    "providers.update_config": set(),
    "openapi_connections.create": set(),
    "openapi_connections.update": set(),
    "mcp_servers.create_spec": set(),
    "mcp_servers.update_spec": set(),
    "mcp_servers.create": set(),
    "mcp_servers.update": set(),
    "skills.create": set(),
    "skills.create_from_archive": set(),
    "skills.import_from_github": set(),
    "skills.edit_metadata": set(),
    "skills.edit_content": set(),
    # ``TriggerCreate`` is a unified DTO covering cron + webhook + polling; each
    # toolset method exposes only its variant's relevant fields and hardcodes
    # ``trigger_type``.
    "triggers.create_cron": {
        "trigger_type",
        "data_extractor",
        "data_extractor_config",
        "webhook_id",
        "allowed_methods",
        "webhook_type",
        "validation_rules",
        "webhook_config",
        "event_types",
        "channel_credentials",
    },
    "triggers.create_webhook": {
        "trigger_type",
        "cron_expression",
        "timezone",
        "data_extractor",
        "data_extractor_config",
        "validation_rules",
        "webhook_config",
        "channel_credentials",
    },
}

# Path-like kwargs that name an entity ID rather than a body field. Allowed
# even if the DTO has no field with that name. If a DTO *does* have a field
# of the same name (e.g. ``RunCreate.project_id``), the kwarg is treated as a
# field — not as a path-like — and must be exposed normally.
PATH_LIKE_KWARGS = {
    "agent_id",
    "config_id",
    "connection_id",
    "id",
    "instance_id",
    "project_id",
    "run_id",
    "skill_id",
    "spec_id",
    "trigger_id",
}


def _kwarg_names(method: Callable) -> set[str]:
    sig = inspect.signature(method)
    return {name for name in sig.parameters if name != "self"}


def _normalize_kwargs(kwargs: set[str], fields: set[str]) -> set[str]:
    """Apply the ``foo_json`` → ``foo`` aliasing rule.

    JSON-typed DTO fields (e.g. ``spec_content``, ``custom_headers``,
    ``json_spec``) are exposed on the toolset as ``{name}_json`` string kwargs
    so LLMs can pass JSON-encoded strings directly. The toolset decodes them
    before constructing the Pydantic model. For parity purposes, treat
    ``foo_json`` as if it were ``foo``.
    """
    normalized: set[str] = set()
    for kw in kwargs:
        if kw.endswith("_json") and kw[: -len("_json")] in fields:
            normalized.add(kw[: -len("_json")])
        else:
            normalized.add(kw)
    return normalized


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p.label)
def test_toolset_kwargs_are_subset_of_dto_fields(pair: Pair) -> None:
    raw_kwargs = _kwarg_names(pair.method)
    fields = set(pair.model.model_fields.keys())
    aliased = _normalize_kwargs(raw_kwargs, fields)
    # Drop path-like kwargs only when they aren't real DTO fields. A kwarg
    # like ``project_id`` may be path-like in one pair but a body field in
    # another; let the DTO decide.
    kwargs = {k for k in aliased if k in fields or k not in PATH_LIKE_KWARGS}

    extras = kwargs - fields
    assert not extras, (
        f"{pair.label}: toolset method exposes kwargs {sorted(extras)} "
        f"that don't exist on {pair.model.__name__}. "
        "Either rename the kwarg, add the field to the DTO, or remove the kwarg."
    )


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p.label)
def test_toolset_uncovered_fields_match_declaration(pair: Pair) -> None:
    """Any DTO field NOT exposed as a kwarg must be listed in UNCOVERED_FIELDS.

    This forces the omission to be explicit when a new field is added to the
    DTO — either you expose it as a kwarg, or you justify the gap by adding
    it to the per-pair allow-list above.
    """
    raw_kwargs = _kwarg_names(pair.method)
    fields = set(pair.model.model_fields.keys())
    aliased = _normalize_kwargs(raw_kwargs, fields)
    # Drop path-like kwargs only when they aren't real DTO fields. A kwarg
    # like ``project_id`` may be path-like in one pair but a body field in
    # another; let the DTO decide.
    kwargs = {k for k in aliased if k in fields or k not in PATH_LIKE_KWARGS}

    declared_uncovered = UNCOVERED_FIELDS.get(pair.label, set())
    actual_uncovered = fields - kwargs
    undeclared_gap = actual_uncovered - declared_uncovered
    assert not undeclared_gap, (
        f"{pair.label}: DTO fields {sorted(undeclared_gap)} are not exposed as "
        f"toolset kwargs and not declared in UNCOVERED_FIELDS. "
        "Either expose them or add to the allow-list."
    )
    obsolete = declared_uncovered - fields
    assert not obsolete, (
        f"{pair.label}: UNCOVERED_FIELDS lists {sorted(obsolete)} which no "
        f"longer exist on {pair.model.__name__}. Clean up the allow-list."
    )
