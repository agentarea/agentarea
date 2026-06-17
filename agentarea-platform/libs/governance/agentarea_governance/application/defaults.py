"""Baseline policy provisioning for new workspaces.

The default policy set is DATA (``config/default_policies.yaml``), not a code
constant — edit the file or point ``GOVERNANCE_DEFAULT_POLICIES_PATH`` at
another one to change what a new workspace starts with. This module only reads
that data and turns it into ``PolicyRule`` rows for a given workspace.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..domain.rules import PolicyEffect, PolicyRule, PolicySubjectType

if TYPE_CHECKING:
    from .service import GovernancePolicyService

logger = logging.getLogger(__name__)

_ENV_PATH_VAR = "GOVERNANCE_DEFAULT_POLICIES_PATH"
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "default_policies.yaml"


def _config_path(path: Path | None) -> Path:
    if path is not None:
        return path
    override = os.getenv(_ENV_PATH_VAR)
    return Path(override) if override else _DEFAULT_CONFIG_PATH


def load_default_policy_specs(path: Path | None = None) -> list[dict[str, Any]]:
    """Read the raw default-policy specs from the YAML config.

    Returns an empty list when the file is absent so a missing config simply
    means "new workspaces start empty" rather than an error.
    """
    resolved = _config_path(path)
    if not resolved.exists():
        logger.info("no default policies file at %s; workspaces start empty", resolved)
        return []

    data = yaml.safe_load(resolved.read_text()) or {}
    specs = data.get("policies", [])
    if not isinstance(specs, list):
        raise ValueError(f"'policies' in {resolved} must be a list, got {type(specs).__name__}")
    return specs


def default_policy_rules(workspace_id: str, path: Path | None = None) -> list[PolicyRule]:
    """Build the workspace-scoped baseline ``PolicyRule`` rows from config."""
    rules: list[PolicyRule] = []
    for spec in load_default_policy_specs(path):
        rules.append(
            PolicyRule(
                subject_type=PolicySubjectType.WORKSPACE,
                subject_id=workspace_id,
                target=spec["target"],
                effect=PolicyEffect(spec["effect"]),
                params=spec.get("params", {}),
                condition=spec.get("condition"),
                enabled=spec.get("enabled", True),
                priority=spec.get("priority", 0),
            )
        )
    return rules


def _dimension_key(target: str, effect: PolicyEffect | str, params: dict[str, Any]) -> tuple:
    """Identity of a baseline dimension, fine enough to tell apart the two spend
    caps (month vs run) which share ``(target, effect)`` but differ by period."""
    return (target, str(effect), params.get("period"))


async def provision_default_policies(
    service: GovernancePolicyService,
    workspace_id: str,
    *,
    path: Path | None = None,
) -> list[PolicyRule]:
    """Idempotently seed the missing baseline dimensions for ``workspace_id``.

    Only baseline dimensions the workspace does not already have are added, keyed
    by ``(target, effect, period)``. A dimension the user already configured
    (e.g. their own monthly spend cap) is left untouched, while the rest of the
    baseline still gets filled in. Safe to call repeatedly.
    """
    existing = await service.list_rules(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id=workspace_id,
    )
    existing_keys = {_dimension_key(r.target, r.effect, r.params) for r in existing}

    created: list[PolicyRule] = []
    for rule in default_policy_rules(workspace_id, path):
        if _dimension_key(rule.target, rule.effect, rule.params) in existing_keys:
            continue
        created.append(await service.create_rule(rule=rule, subject_id=rule.subject_id))
    if created:
        logger.info("seeded %d default policies for workspace %s", len(created), workspace_id)
    return created
