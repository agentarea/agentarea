"""Analyze a package source into an :class:`ImportPreview`.

Parsing (text -> :class:`Bundle`) is deterministic and pure. Analysis
adds structural validation (key references, unsupported MCPs, setup
placeholders) and per-entity existence status. Existence checks are delegated
to an :class:`ExistenceChecker` so the analyzer stays decoupled from the
repository layer and is trivially testable.
"""

from __future__ import annotations

from typing import Any, Protocol

import yaml
from pydantic import ValidationError

from agentarea_bundles.schemas.bundle import Bundle, BundleMcp, setup_refs
from agentarea_bundles.schemas.preview import (
    EntityKind,
    EntityStatus,
    ImportPreview,
    IssueSeverity,
    PreviewEntity,
    PreviewIssue,
)

# Commands we can run inside the mcp-bridge container. Anything else (an
# absolute path, a ${CLAUDE_PLUGIN_ROOT}-relative binary shipped with a plugin)
# cannot be provisioned in our container runtime and is marked unsupported.
_SUPPORTED_COMMANDS = {"npx", "uvx", "uv", "python", "python3", "node", "bunx", "deno"}


class BundleParseError(ValueError):
    """Raised when source text is not a valid agent package."""


class ExistenceChecker(Protocol):
    """Workspace existence checks used to compute per-entity status."""

    async def agent_exists(self, name: str) -> bool: ...
    async def mcp_instance_exists(self, name: str) -> bool: ...
    async def skill_exists(self, name: str) -> bool: ...
    async def trigger_exists(self, name: str) -> bool: ...


class _NoExistence:
    """Default checker: nothing pre-exists (everything will be created)."""

    async def agent_exists(self, name: str) -> bool:
        return False

    async def mcp_instance_exists(self, name: str) -> bool:
        return False

    async def skill_exists(self, name: str) -> bool:
        return False

    async def trigger_exists(self, name: str) -> bool:
        return False


def parse_bundle(text: str) -> Bundle:
    """Parse YAML or JSON source text into a canonical :class:`Bundle`.

    YAML is a superset of JSON, so a single loader handles both authoring forms.
    """
    if not text or not text.strip():
        raise BundleParseError("empty package source")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BundleParseError(f"invalid YAML/JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BundleParseError("package must be a mapping at the top level")
    try:
        return Bundle.model_validate(data)
    except ValidationError as exc:
        raise BundleParseError(str(exc)) from exc


def mcp_is_unsupported(mcp: BundleMcp) -> str | None:
    """Return a reason string if this MCP cannot run in our runtime, else None."""
    spec = mcp.json_spec or {}
    spec_type = spec.get("type")
    if spec_type != "command":
        return None  # docker/url always supported
    command = (spec.get("command") or "").strip()
    if not command:
        return "command MCP has no 'command'"
    if "${CLAUDE_PLUGIN_ROOT}" in command or "$CLAUDE_PLUGIN_ROOT" in command:
        return "command references a plugin-local binary (${CLAUDE_PLUGIN_ROOT}); not available in the container runtime"
    if command.startswith(("/", "./", "../")):
        return f"command '{command}' is a local path; only published runtimes ({', '.join(sorted(_SUPPORTED_COMMANDS))}) are supported"
    if command not in _SUPPORTED_COMMANDS:
        return f"command '{command}' is not a supported runtime ({', '.join(sorted(_SUPPORTED_COMMANDS))})"
    return None


class BundleAnalyzer:
    """Builds an :class:`ImportPreview` from an :class:`Bundle`."""

    def __init__(self, existence: ExistenceChecker | None = None) -> None:
        self._existence = existence or _NoExistence()

    async def analyze(self, package: Bundle) -> ImportPreview:
        issues: list[PreviewIssue] = []
        entities: list[PreviewEntity] = []

        setup_keys = {f.key for f in package.setup}
        mcp_keys = {m.key for m in package.mcps}
        skill_keys = {s.key for s in package.skills}
        agent_keys = {a.key for a in package.agents}

        self._check_duplicate_keys(package, issues)
        unsupported_mcp_keys = self._analyze_mcps(package, setup_keys, entities, issues)
        await self._analyze_skills(package, entities)
        self._analyze_agents(
            package, mcp_keys, skill_keys, setup_keys, unsupported_mcp_keys, issues
        )
        await self._populate_agent_entities(package, entities)
        await self._analyze_automations(package, agent_keys, entities, issues)
        self._analyze_policies(package, agent_keys, entities, issues)

        installable = not any(i.severity is IssueSeverity.BLOCK for i in issues)
        return ImportPreview(
            bundle=package,
            setup=package.setup,
            entities=entities,
            issues=issues,
            installable=installable,
        )

    # -- sections -----------------------------------------------------------

    def _check_duplicate_keys(self, package: Bundle, issues: list[PreviewIssue]) -> None:
        for label, items in (
            ("setup", package.setup),
            ("mcp", package.mcps),
            ("skill", package.skills),
            ("agent", package.agents),
            ("automation", package.automations),
            ("policy", package.policies),
        ):
            seen: set[str] = set()
            for item in items:
                if item.key in seen:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=f"duplicate {label} key '{item.key}'",
                            entity_key=item.key,
                        )
                    )
                seen.add(item.key)

    def _analyze_mcps(
        self,
        package: Bundle,
        setup_keys: set[str],
        entities: list[PreviewEntity],
        issues: list[PreviewIssue],
    ) -> set[str]:
        unsupported: set[str] = set()
        for mcp in package.mcps:
            reason = mcp_is_unsupported(mcp)
            # bindings must reference declared setup fields
            for env_name, ref in mcp.bindings.items():
                refs = setup_refs(ref)
                if not refs:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=f"mcp '{mcp.key}' binding '{env_name}' must reference ${{setup.<key>}}",
                            entity_key=mcp.key,
                        )
                    )
                for key in refs:
                    if key not in setup_keys:
                        issues.append(
                            PreviewIssue(
                                severity=IssueSeverity.BLOCK,
                                message=f"mcp '{mcp.key}' binding references unknown setup field '{key}'",
                                entity_key=mcp.key,
                            )
                        )
            if reason:
                unsupported.add(mcp.key)
                entities.append(
                    PreviewEntity(
                        kind=EntityKind.MCP,
                        key=mcp.key,
                        name=mcp.name,
                        status=EntityStatus.UNSUPPORTED,
                        detail=reason,
                    )
                )
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.WARN,
                        message=f"mcp '{mcp.key}' will be skipped: {reason}",
                        entity_key=mcp.key,
                    )
                )
            else:
                entities.append(
                    PreviewEntity(
                        kind=EntityKind.MCP,
                        key=mcp.key,
                        name=mcp.name,
                        status=EntityStatus.WILL_CREATE,  # refined for existence below
                    )
                )
        return unsupported

    async def _analyze_skills(self, package: Bundle, entities: list[PreviewEntity]) -> None:
        for skill in package.skills:
            exists = await self._existence.skill_exists(skill.name)
            entities.append(
                PreviewEntity(
                    kind=EntityKind.SKILL,
                    key=skill.key,
                    name=skill.name,
                    status=EntityStatus.ALREADY_EXISTS if exists else EntityStatus.WILL_CREATE,
                )
            )

    def _analyze_agents(
        self,
        package: Bundle,
        mcp_keys: set[str],
        skill_keys: set[str],
        setup_keys: set[str],
        unsupported_mcp_keys: set[str],
        issues: list[PreviewIssue],
    ) -> None:
        for agent in package.agents:
            for ref in agent.mcps:
                if ref not in mcp_keys:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=f"agent '{agent.key}' references unknown mcp '{ref}'",
                            entity_key=agent.key,
                        )
                    )
                elif ref in unsupported_mcp_keys:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.WARN,
                            message=f"agent '{agent.key}' depends on unsupported mcp '{ref}'; it will be created without that tool",
                            entity_key=agent.key,
                        )
                    )
            for ref in agent.skills:
                if ref not in skill_keys:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=f"agent '{agent.key}' references unknown skill '{ref}'",
                            entity_key=agent.key,
                        )
                    )
            if not agent.model:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=f"agent '{agent.key}' has no model",
                        entity_key=agent.key,
                    )
                )
            else:
                for key in setup_refs(agent.model):
                    if key not in setup_keys:
                        issues.append(
                            PreviewIssue(
                                severity=IssueSeverity.BLOCK,
                                message=f"agent '{agent.key}' model references unknown setup field '{key}'",
                                entity_key=agent.key,
                            )
                        )

    async def _populate_agent_entities(
        self, package: Bundle, entities: list[PreviewEntity]
    ) -> None:
        for agent in package.agents:
            exists = await self._existence.agent_exists(agent.name)
            entities.append(
                PreviewEntity(
                    kind=EntityKind.AGENT,
                    key=agent.key,
                    name=agent.name,
                    status=EntityStatus.ALREADY_EXISTS if exists else EntityStatus.WILL_CREATE,
                )
            )

    async def _analyze_automations(
        self,
        package: Bundle,
        agent_keys: set[str],
        entities: list[PreviewEntity],
        issues: list[PreviewIssue],
    ) -> None:
        for auto in package.automations:
            if auto.agent not in agent_keys:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=f"automation '{auto.key}' references unknown agent '{auto.agent}'",
                        entity_key=auto.key,
                    )
                )
            exists = await self._existence.trigger_exists(auto.key)
            entities.append(
                PreviewEntity(
                    kind=EntityKind.AUTOMATION,
                    key=auto.key,
                    name=auto.key,
                    status=EntityStatus.ALREADY_EXISTS if exists else EntityStatus.WILL_CREATE,
                    detail=f"cron '{auto.cron}' ({auto.timezone}), enabled={auto.enabled}",
                )
            )

    def _analyze_policies(
        self,
        package: Bundle,
        agent_keys: set[str],
        entities: list[PreviewEntity],
        issues: list[PreviewIssue],
    ) -> None:
        for policy in package.policies:
            if policy.subject != "workspace" and policy.subject not in agent_keys:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=(
                            f"policy '{policy.key}' subject '{policy.subject}' is neither "
                            f"'workspace' nor a known agent key"
                        ),
                        entity_key=policy.key,
                    )
                )
            entities.append(
                PreviewEntity(
                    kind=EntityKind.POLICY,
                    key=policy.key,
                    name=policy.key,
                    status=EntityStatus.WILL_CREATE,
                    detail=f"{policy.effect} {policy.target} on {policy.subject}",
                )
            )


def required_setup_errors(package: Bundle, setup_values: dict[str, Any]) -> list[PreviewIssue]:
    """Block issues for required setup fields missing a value (checked at install)."""
    issues: list[PreviewIssue] = []
    for field in package.setup:
        if not field.required:
            continue
        value = setup_values.get(field.key, field.default)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            issues.append(
                PreviewIssue(
                    severity=IssueSeverity.BLOCK,
                    message=f"required setup field '{field.key}' is missing",
                    entity_key=field.key,
                )
            )
    return issues
