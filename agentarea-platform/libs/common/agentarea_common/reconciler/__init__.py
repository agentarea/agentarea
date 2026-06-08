"""IaC config reconciler module.

Only the YAML parsers remain here. The legacy ``ReconcilerService`` (YAML -> DB
entity materializer that seeded built-ins into the platform workspace) was
removed: built-in agents/skills and the reference specs mcp_servers/model_specs
are catalog-only (ADR-003), read globally from the registry catalog and never
materialized into a workspace-owned row.
"""

from .parsers import YAMLValidationError, parse_yaml

__all__ = ["YAMLValidationError", "parse_yaml"]
