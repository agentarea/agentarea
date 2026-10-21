"""Analyze a package source into an :class:`ImportPreview`.

Parsing (text -> :class:`Bundle`) is deterministic and pure. Analysis
adds structural validation (key references, unsupported MCPs, setup
placeholders) and per-entity existence status. Existence checks are delegated
to an :class:`ExistenceChecker` so the analyzer stays decoupled from the
repository layer and is trivially testable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from typing import Any, Protocol

import yaml
from agentarea_agents.application.skill_parser import SkillParser
from agentarea_common.utils.untrusted_yaml import load_untrusted_yaml
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    assert_enforceable,
)
from pydantic import BaseModel, ValidationError

from agentarea_bundles.schemas.bundle import (
    MAX_NAME_LENGTH,
    Bundle,
    BundleAutomation,
    BundleChannel,
    BundleMcp,
    BundlePolicy,
    BundleSkill,
    SetupFieldType,
    resolve_placeholders,
    setup_refs,
)
from agentarea_bundles.schemas.preview import (
    EntityKind,
    EntityStatus,
    ImportPreview,
    IssueSeverity,
    PreviewEntity,
    PreviewIssue,
)
from agentarea_bundles.schemas.result import InstallAction, InstalledEntity, InstallResult

# Commands we can run inside the MCP base image. Anything else (an
# absolute path, a ${CLAUDE_PLUGIN_ROOT}-relative binary shipped with a plugin)
# cannot be provisioned in our container runtime and is marked unsupported.
_SUPPORTED_COMMANDS = {"npx", "uvx", "uv", "python", "python3", "node", "bunx", "deno"}


class BundleParseError(ValueError):
    """Raised when source text is not a valid agent package."""


class ExistenceChecker(Protocol):
    """Workspace lookups used to compute per-entity status; ``find_*`` return the id."""

    async def find_agent(self, name: str) -> str | None: ...
    async def find_mcp_instance(self, name: str) -> str | None: ...
    async def find_skill(self, name: str) -> str | None: ...
    async def find_trigger(self, name: str) -> str | None: ...
    async def ref_exists(self, kind: EntityKind, entity_id: str) -> bool: ...
    async def channel_credential_keys(self, entity_id: str) -> set[str] | None: ...


@dataclass(frozen=True)
class CatalogMcp:
    """The catalog server a bundle MCP's ``catalog`` id names."""

    spec_id: str
    transport: str | None  # None when the catalog entry declares no way to reach it


class DeployChecks(Protocol):
    """Questions only the workspace can answer, asked of every write a plan makes."""

    async def catalog_mcp(self, catalog_id: str) -> CatalogMcp | None: ...
    async def agent_problem(self, model_id: str, toolsets: list[str]) -> str | None: ...
    async def automation_problem(
        self, package: Bundle, automation: BundleAutomation
    ) -> str | None: ...
    async def may_edit(self, kind: EntityKind, entity_id: str) -> bool: ...


# Entities whose update needs per-object edit permission. A policy write is
# workspace-admin gated; an MCP server is never updated.
EDIT_GUARDED = (EntityKind.SKILL, EntityKind.AGENT, EntityKind.CHANNEL, EntityKind.AUTOMATION)
_WRITES = (EntityStatus.WILL_CREATE, EntityStatus.WILL_UPDATE)

# Actions meaning "this bundle created the entity", so a redeploy may change it.
# A skipped entry carries an id only when a key this bundle created was skipped.
_OWNED_ACTIONS = {
    InstallAction.CREATED,
    InstallAction.UPDATED,
    InstallAction.UNCHANGED,
    InstallAction.ORPHANED,
    InstallAction.SKIPPED,
}
# Actions under which dependants were pointed at the entity's id.
_LINKED_ACTIONS = {
    InstallAction.CREATED,
    InstallAction.UPDATED,
    InstallAction.UNCHANGED,
    InstallAction.REUSED,
}

MCP_NOT_APPLIED = "changes not applied: MCP servers are not updated on redeploy yet"
GITHUB_SKILL_NOT_APPLIED = "changes not applied: a GitHub skill is not re-imported on redeploy"
ORPHANED_DETAIL = "removed from the bundle; left in place, not deleted"


def bundle_entities(package: Bundle, kind: EntityKind) -> list[Any]:
    return {
        EntityKind.MCP: package.mcps,
        EntityKind.SKILL: package.skills,
        EntityKind.AGENT: package.agents,
        EntityKind.CHANNEL: package.channels,
        EntityKind.AUTOMATION: package.automations,
        EntityKind.POLICY: package.policies,
    }[kind]


def trigger_name(package: Bundle, key: str) -> str:
    return f"{package.name}:{key}"


def _resolve_tree(value: Any, values: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return resolve_placeholders(value, values)
    if isinstance(value, dict):
        return {k: _resolve_tree(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_tree(v, values) for v in value]
    return value


def _secret_keys(package: Bundle) -> set[str]:
    return {f.key for f in package.setup if f.type is SetupFieldType.SECRET}


def given(value: Any) -> bool:
    """A setup value counts as supplied unless it is missing or a blank string."""
    return value is not None and not (isinstance(value, str) and value.strip() == "")


def supplied_keys(supplied: dict[str, Any]) -> set[str]:
    return {k for k, v in supplied.items() if given(v)}


def effective_setup(
    package: Bundle, supplied: dict[str, Any], prior: PriorInstall | None
) -> dict[str, Any]:
    """Setup values in force: field defaults, then remembered ones, then supplied ones."""
    values = {f.key: f.default for f in package.setup if given(f.default)}
    values.update(remembered_setup(package, {}, prior))
    values.update({k: v for k, v in supplied.items() if given(v)})
    return values


def remembered_setup(
    package: Bundle, supplied: dict[str, Any], prior: PriorInstall | None
) -> dict[str, Any]:
    """Non-secret values supplied to this and earlier installs, kept for the next redeploy."""
    public = {f.key for f in package.setup} - _secret_keys(package)
    merged = {**(prior.result.setup_values if prior else {}), **supplied}
    return {k: v for k, v in merged.items() if k in public and given(v)}


def spec_fingerprint(package: Bundle, spec: BaseModel, values: dict[str, Any]) -> str:
    """sha256 of ``spec`` with its non-secret setup placeholders resolved."""
    secret = _secret_keys(package)
    public = {k: v for k, v in values.items() if k not in secret}
    resolved = _resolve_tree(spec.model_dump(mode="json"), public)
    return hashlib.sha256(json.dumps(resolved, sort_keys=True, default=str).encode()).hexdigest()


def channel_credentials(
    channel: BundleChannel, values: dict[str, Any], supplied: Collection[str] | None = None
) -> dict[str, str]:
    """The channel's bound credentials that resolve fully from ``values``.

    With ``supplied``, only bindings whose setup keys were all given this deploy:
    a redeploy rewrites what the caller handed over and nothing else.
    """
    credentials: dict[str, str] = {}
    for name, ref in channel.bindings.items():
        refs = setup_refs(ref)
        if supplied is not None and not (refs and all(k in supplied for k in refs)):
            continue
        value = resolve_placeholders(ref, values)
        if not setup_refs(value):
            credentials[name] = value
    return credentials


def _refs_in(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(setup_refs(value))
    if isinstance(value, dict):
        return set().union(*(_refs_in(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_refs_in(v) for v in value))
    return set()


def linked_id(result: InstallResult, kind: EntityKind, key: str) -> str | None:
    """The id dependants of ``key`` were pointed at by ``result``, if any."""
    return next(
        (
            e.id
            for e in result.entities
            if e.kind is kind and e.key == key and e.action in _LINKED_ACTIONS
        ),
        None,
    )


@dataclass(frozen=True)
class PriorInstall:
    """What the last install of a bundle declared and what it left in the workspace."""

    bundle: Bundle
    result: InstallResult

    @classmethod
    def from_record(
        cls, canonical: dict[str, Any], install_result: dict[str, Any] | None
    ) -> PriorInstall:
        bundle = Bundle.model_validate(canonical)
        if install_result is None:
            return cls(bundle=bundle, result=InstallResult(bundle_name=bundle.name))
        return cls(bundle=bundle, result=InstallResult.model_validate(install_result))

    def owned(self, kind: EntityKind, key: str) -> InstalledEntity | None:
        """The entity this bundle created for ``key``, if it created one."""
        return next(
            (
                e
                for e in self.result.entities
                if e.kind is kind and e.key == key and e.id and e.action in _OWNED_ACTIONS
            ),
            None,
        )

    def spec(self, kind: EntityKind, key: str) -> Any | None:
        """What the last install declared for ``key``."""
        return next((i for i in bundle_entities(self.bundle, kind) if i.key == key), None)

    def owned_entities(self) -> list[InstalledEntity]:
        return [e for e in self.result.entities if e.id and e.action in _OWNED_ACTIONS]

    def fingerprint(self, kind: EntityKind, key: str) -> str | None:
        """What was last applied to ``key``; a record predating fingerprints derives it."""
        ref = self.owned(kind, key)
        if ref is None:
            return None
        if ref.fingerprint is not None:
            return ref.fingerprint
        spec = next((i for i in bundle_entities(self.bundle, kind) if i.key == key), None)
        if spec is None:
            return None
        defaults = {f.key: f.default for f in self.bundle.setup if given(f.default)}
        return spec_fingerprint(self.bundle, spec, {**defaults, **self.result.setup_values})

    def changed(self, kind: EntityKind, key: str, fingerprint: str) -> bool:
        return self.fingerprint(kind, key) != fingerprint

    def deps_changed(
        self,
        depends_on: list[tuple[EntityKind, str]],
        current: Callable[[EntityKind, str], str | None],
    ) -> bool:
        """A dependency now resolves to another id than the one this install linked."""
        return any(
            current(kind, key) != linked_id(self.result, kind, key) for kind, key in depends_on
        )


class _NoExistence:
    """Default checker: nothing pre-exists (everything will be created)."""

    async def find_agent(self, name: str) -> str | None:
        return None

    async def find_mcp_instance(self, name: str) -> str | None:
        return None

    async def find_skill(self, name: str) -> str | None:
        return None

    async def find_trigger(self, name: str) -> str | None:
        return None

    async def ref_exists(self, kind: EntityKind, entity_id: str) -> bool:
        return False

    async def channel_credential_keys(self, entity_id: str) -> set[str] | None:
        return None


_BUNDLE_MAX_BYTES = 5 * 1024 * 1024
BUNDLE_MAX_NODES = 200_000


def parse_bundle(text: str) -> Bundle:
    """Parse YAML or JSON source text into a canonical :class:`Bundle`.

    YAML is a superset of JSON, so a single loader handles both authoring forms.
    """
    if not text or not text.strip():
        raise BundleParseError("empty package source")
    try:
        data = load_untrusted_yaml(text, max_nodes=BUNDLE_MAX_NODES, max_bytes=_BUNDLE_MAX_BYTES)
    except yaml.YAMLError as exc:
        raise BundleParseError(f"invalid YAML/JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BundleParseError("package must be a mapping at the top level")
    try:
        return Bundle.model_validate(data)
    except ValidationError as exc:
        raise BundleParseError(str(exc)) from exc


# Stands in for the id of an entity this deploy creates; never equals a recorded one.
_NOT_YET_CREATED = "<created by this deploy>"

# Subject ids are resolved at install time (an agent key becomes a real id), so
# analysis validates the rule with a stand-in. assert_enforceable never inspects
# the id — only the subject *type*, which the policy's own `subject` determines.
_PLACEHOLDER_SUBJECT_ID = "00000000-0000-0000-0000-000000000000"


def policy_as_rule(policy: BundlePolicy, subject_id: str) -> PolicyRule:
    """Build the governance rule a bundle policy installs as.

    Shared by the analyzer and the installer so the rule that gets validated at
    preview time is the same object that gets written.

    ``message`` is deliberately not folded into ``params``: nothing reads it
    there, and the typed param models forbid extras, so carrying it would make
    every cap/approval rule fail validation.
    """
    return PolicyRule(
        enabled=policy.enabled,
        priority=policy.priority,
        subject_type=(
            PolicySubjectType.WORKSPACE
            if policy.subject == "workspace"
            else PolicySubjectType.AGENT
        ),
        subject_id=subject_id,
        target=policy.target,
        effect=PolicyEffect(policy.effect),
        params=dict(policy.params),
        condition=policy.condition,
    )


def mcp_is_unsupported(mcp: BundleMcp) -> str | None:
    """Return a reason string if this MCP cannot run in our runtime, else None."""
    if mcp.catalog is not None:
        return None  # the catalog's connect flow decides
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


def _json_spec_setup_refs(json_spec: dict[str, Any] | None) -> list[str]:
    """Setup keys referenced from the transport values the installer resolves."""
    if not json_spec:
        return []
    values: list[Any] = [json_spec.get("endpoint_url"), json_spec.get("url")]
    args = json_spec.get("args")
    if isinstance(args, list):
        values.extend(args)
    return [key for value in values for key in setup_refs(value)]


def skill_main_file(files: dict[str, str]) -> str | None:
    """The root SKILL.md of a files skill, matched the way the skill service matches it."""
    return SkillParser().find_main_skill_file(list(files))


class BundleAnalyzer:
    """Builds an :class:`ImportPreview` from an :class:`Bundle`."""

    def __init__(
        self,
        existence: ExistenceChecker | None = None,
        prior: PriorInstall | None = None,
        setup_values: dict[str, Any] | None = None,
        checks: DeployChecks | None = None,
    ) -> None:
        self._existence = existence or _NoExistence()
        self._prior = prior
        self._checks = checks
        self._supplied = setup_values or {}
        self._planned: dict[tuple[EntityKind, str], EntityStatus] = {}
        self._ids: dict[tuple[EntityKind, str], str | None] = {}
        self._unfinished_channels: set[str] = set()
        self._package: Bundle
        self._values: dict[str, Any]
        # Setup keys this deploy writes; None on a first install, which needs every required one.
        self.needed_setup: set[str] | None = None

    async def analyze(self, package: Bundle) -> ImportPreview:
        issues: list[PreviewIssue] = []
        entities: list[PreviewEntity] = []
        self._planned = {}
        self._ids = {}
        self._unfinished_channels = set()
        self._package = package
        self._values = effective_setup(package, self._supplied, self._prior)

        setup_keys = {f.key for f in package.setup}
        mcp_keys = {m.key for m in package.mcps}
        skill_keys = {s.key for s in package.skills}
        agent_keys = {a.key for a in package.agents}

        self._check_duplicate_keys(package, issues)
        unsupported_mcp_keys = await self._analyze_mcps(package, setup_keys, entities, issues)
        await self._check_context_secrets(package, issues)
        await self._analyze_skills(package, entities, issues)
        self._analyze_agents(
            package, mcp_keys, skill_keys, setup_keys, unsupported_mcp_keys, issues
        )
        await self._populate_agent_entities(package, entities)
        await self._analyze_channels(package, agent_keys, setup_keys, entities, issues)
        await self._analyze_automations(package, agent_keys, entities, issues)
        await self._analyze_policies(package, agent_keys, entities, issues)
        self._check_trigger_names(package, issues)
        await self._report_orphans(package, entities)
        if self._checks is not None:
            await self._check_writes(package, self._checks, issues)

        self.needed_setup = needed = self._needed_setup(package)
        setup = package.setup
        if needed is not None:
            setup = [
                f.model_copy(
                    update={
                        "required": f.required and f.key in needed and f.key not in self._values
                    }
                )
                for f in package.setup
            ]
        installable = not any(i.severity is IssueSeverity.BLOCK for i in issues)
        return ImportPreview(
            bundle=package,
            setup=setup,
            entities=entities,
            issues=issues,
            installable=installable,
        )

    # -- plan -----------------------------------------------------------------

    def _prior_spec(self, kind: EntityKind, key: str) -> Any | None:
        return self._prior.spec(kind, key) if self._prior and self._prior.owned(kind, key) else None

    def _supplied_keys(self) -> set[str]:
        return supplied_keys(self._supplied)

    def _needed_setup(self, package: Bundle) -> set[str] | None:
        """Setup keys the planned writes resolve: all of a new entity's, an updated agent's model."""
        if self._prior is None:
            return None
        needed: set[str] = set()
        for kind in EntityKind:
            for item in bundle_entities(package, kind):
                status = self._planned.get((kind, item.key))
                if status is EntityStatus.WILL_CREATE:
                    needed |= _refs_in(item.model_dump(mode="json"))
                elif status is EntityStatus.WILL_UPDATE and kind is EntityKind.AGENT:
                    needed |= set(setup_refs(item.model))
                elif kind is EntityKind.CHANNEL and item.key in self._unfinished_channels:
                    needed |= _refs_in(item.bindings)
        return needed

    async def _plan(
        self,
        kind: EntityKind,
        spec: Any,
        find_by_name: Callable[[], Awaitable[str | None]] | None = None,
        depends_on: list[tuple[EntityKind, str]] | None = None,
    ) -> EntityStatus:
        """Status of one entity against the previous install of this bundle.

        An entity the bundle created before is updated when its resolved spec
        changed or something it points at now resolves to another id; one it
        never created is reused by name, as on a first install.
        """
        prior = self._prior
        owned = prior.owned(kind, spec.key) if prior else None
        if (
            prior is not None
            and owned is not None
            and owned.id
            and await self._existence.ref_exists(kind, owned.id)
        ):
            self._ids[(kind, spec.key)] = owned.id
            fingerprint = spec_fingerprint(self._package, spec, self._values)
            if prior.changed(kind, spec.key, fingerprint) or prior.deps_changed(
                depends_on or [], lambda k, key: self._ids.get((k, key))
            ):
                status = EntityStatus.WILL_UPDATE
            else:
                status = EntityStatus.UNCHANGED
        else:
            found = await find_by_name() if find_by_name is not None else None
            if found is not None:
                status = EntityStatus.ALREADY_EXISTS
                self._ids[(kind, spec.key)] = found
            else:
                status = EntityStatus.WILL_CREATE
                self._ids[(kind, spec.key)] = _NOT_YET_CREATED
        self._planned[(kind, spec.key)] = status
        return status

    async def _check_writes(
        self, package: Bundle, checks: DeployChecks, issues: list[PreviewIssue]
    ) -> None:
        """Refuse up front what a write would refuse halfway through the install."""
        for agent in package.agents:
            if self._planned.get((EntityKind.AGENT, agent.key)) not in _WRITES:
                continue
            model_id = resolve_placeholders(agent.model or "", self._values)
            optional = [
                key
                for key in setup_refs(model_id)
                if (field := package.setup_field(key)) is not None and not field.required
            ]
            if optional:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=(
                            f"agent '{agent.key}': model needs setup field(s) "
                            f"{', '.join(optional)}, which have no value"
                        ),
                        entity_key=agent.key,
                    )
                )
            if not model_id or setup_refs(model_id):
                continue
            problem = await checks.agent_problem(model_id, agent.toolsets)
            if problem:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=f"agent '{agent.key}': {problem}",
                        entity_key=agent.key,
                    )
                )
        for auto in package.automations:
            if self._planned.get((EntityKind.AUTOMATION, auto.key)) not in _WRITES:
                continue
            problem = await checks.automation_problem(package, auto)
            if problem:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=f"automation '{auto.key}': {problem}",
                        entity_key=auto.key,
                    )
                )
        for kind in EDIT_GUARDED:
            for item in bundle_entities(package, kind):
                entity_id = self._ids.get((kind, item.key))
                if self._planned.get((kind, item.key)) is not EntityStatus.WILL_UPDATE:
                    continue
                if entity_id is None or not await checks.may_edit(kind, entity_id):
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=(
                                f"{kind} '{item.key}' would be updated, but you may not edit "
                                f"{kind} {entity_id}"
                            ),
                            entity_key=item.key,
                        )
                    )

    async def _report_orphans(self, package: Bundle, entities: list[PreviewEntity]) -> None:
        if self._prior is None:
            return
        for ref in self._prior.owned_entities():
            if any(i.key == ref.key for i in bundle_entities(package, ref.kind)):
                continue
            if ref.id is None or not await self._existence.ref_exists(ref.kind, ref.id):
                continue
            entities.append(
                PreviewEntity(
                    kind=ref.kind,
                    key=ref.key,
                    name=ref.name,
                    status=EntityStatus.ORPHANED,
                    detail=ORPHANED_DETAIL,
                )
            )

    # -- sections -----------------------------------------------------------

    def _check_duplicate_keys(self, package: Bundle, issues: list[PreviewIssue]) -> None:
        for label, items in (
            ("setup", package.setup),
            ("mcp", package.mcps),
            ("skill", package.skills),
            ("agent", package.agents),
            ("channel", package.channels),
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

    def _check_trigger_names(self, package: Bundle, issues: list[PreviewIssue]) -> None:
        """Channels and automations become triggers named ``<bundle>:<key>``."""
        for label, items in (("channel", package.channels), ("automation", package.automations)):
            for item in items:
                name = trigger_name(package, item.key)
                if len(name) > MAX_NAME_LENGTH:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=(
                                f"{label} '{item.key}' would create trigger '{name[:40]}...' "
                                f"whose name is longer than {MAX_NAME_LENGTH} characters"
                            ),
                            entity_key=item.key,
                        )
                    )

    async def _mcp_transport(self, mcp: BundleMcp) -> str | None:
        if mcp.json_spec is not None:
            return mcp.json_spec.get("type")
        if self._checks is None or mcp.catalog is None:
            return None
        found = await self._checks.catalog_mcp(mcp.catalog)
        return found.transport if found else None

    async def _check_context_secrets(self, package: Bundle, issues: list[PreviewIssue]) -> None:
        """A context_secret is a URL MCP's, and comes from a secret setup field."""
        for mcp in package.mcps:
            if mcp.context_secret is None:
                continue
            transport = await self._mcp_transport(mcp)
            if transport is not None and transport != "url":
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=f"mcp '{mcp.key}' context_secret applies to url MCPs only",
                        entity_key=mcp.key,
                    )
                )
            for key in setup_refs(mcp.context_secret):
                field = package.setup_field(key)
                if field is None:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=(
                                f"mcp '{mcp.key}' context_secret references unknown "
                                f"setup field '{key}'"
                            ),
                            entity_key=mcp.key,
                        )
                    )
                elif field.type is not SetupFieldType.SECRET:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=(
                                f"mcp '{mcp.key}' context_secret must come from a setup "
                                f"field of type 'secret'; '{key}' is '{field.type}'"
                            ),
                            entity_key=mcp.key,
                        )
                    )

    async def _analyze_mcps(
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
            for key in _json_spec_setup_refs(mcp.json_spec):
                if key not in setup_keys:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=f"mcp '{mcp.key}' json_spec references unknown setup field '{key}'",
                            entity_key=mcp.key,
                        )
                    )
            if mcp.catalog is not None and self._checks is not None:
                found = await self._checks.catalog_mcp(mcp.catalog)
                problem = (
                    f"names catalog server '{mcp.catalog}', which the catalog does not have"
                    if found is None
                    else f"names catalog server '{mcp.catalog}', which declares no transport"
                    if found.transport is None
                    else None
                )
                if problem:
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.BLOCK,
                            message=f"mcp '{mcp.key}' {problem}",
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
                status = await self._plan(
                    EntityKind.MCP,
                    mcp,
                    lambda name=mcp.name: self._existence.find_mcp_instance(name),
                )
                detail = None
                if status is EntityStatus.WILL_UPDATE:
                    status = EntityStatus.CHANGES_NOT_APPLIED
                    detail = MCP_NOT_APPLIED
                    issues.append(
                        PreviewIssue(
                            severity=IssueSeverity.WARN,
                            message=f"mcp '{mcp.key}' changed: {MCP_NOT_APPLIED}",
                            entity_key=mcp.key,
                        )
                    )
                entities.append(
                    PreviewEntity(
                        kind=EntityKind.MCP,
                        key=mcp.key,
                        name=mcp.name,
                        status=status,
                        detail=detail,
                    )
                )
        return unsupported

    async def _analyze_skills(
        self, package: Bundle, entities: list[PreviewEntity], issues: list[PreviewIssue]
    ) -> None:
        for skill in package.skills:
            problem = skill_problem(skill)
            if problem:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=f"skill '{skill.key}' is not a valid SKILL.md: {problem}",
                        entity_key=skill.key,
                    )
                )
            status = await self._plan(
                EntityKind.SKILL,
                skill,
                lambda name=skill.name: self._existence.find_skill(name),
            )
            detail = None
            if status is EntityStatus.WILL_UPDATE and skill.source_type == "github":
                status = EntityStatus.CHANGES_NOT_APPLIED
                detail = GITHUB_SKILL_NOT_APPLIED
                self._planned[(EntityKind.SKILL, skill.key)] = status
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.WARN,
                        message=f"skill '{skill.key}' changed: {GITHUB_SKILL_NOT_APPLIED}",
                        entity_key=skill.key,
                    )
                )
            entities.append(
                PreviewEntity(
                    kind=EntityKind.SKILL,
                    key=skill.key,
                    name=skill.name,
                    status=status,
                    detail=detail,
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
            status = await self._plan(
                EntityKind.AGENT,
                agent,
                lambda name=agent.name: self._existence.find_agent(name),
                depends_on=[
                    *((EntityKind.MCP, ref) for ref in agent.mcps),
                    *((EntityKind.SKILL, ref) for ref in agent.skills),
                ],
            )
            entities.append(
                PreviewEntity(kind=EntityKind.AGENT, key=agent.key, name=agent.name, status=status)
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
            name = trigger_name(package, auto.key)
            status = await self._plan(
                EntityKind.AUTOMATION,
                auto,
                lambda name=name: self._existence.find_trigger(name),
                depends_on=[(EntityKind.AGENT, auto.agent)],
            )
            entities.append(
                PreviewEntity(
                    kind=EntityKind.AUTOMATION,
                    key=auto.key,
                    name=auto.key,
                    status=status,
                    detail=f"cron '{auto.cron}' ({auto.timezone}), enabled={auto.enabled}",
                )
            )

    async def _analyze_channels(
        self,
        package: Bundle,
        agent_keys: set[str],
        setup_keys: set[str],
        entities: list[PreviewEntity],
        issues: list[PreviewIssue],
    ) -> None:
        for channel in package.channels:
            if channel.agent not in agent_keys:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=f"channel '{channel.key}' references unknown agent '{channel.agent}'",
                        entity_key=channel.key,
                    )
                )
            for ref in channel.bindings.values():
                for key in setup_refs(ref):
                    if key not in setup_keys:
                        issues.append(
                            PreviewIssue(
                                severity=IssueSeverity.BLOCK,
                                message=(
                                    f"channel '{channel.key}' binding references unknown "
                                    f"setup field '{key}'"
                                ),
                                entity_key=channel.key,
                            )
                        )
            before = self._prior_spec(EntityKind.CHANNEL, channel.key)
            if isinstance(before, BundleChannel) and before.type != channel.type:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=(
                            f"channel '{channel.key}' changes type from {before.type} to "
                            f"{channel.type}, which a redeploy cannot apply; give it a new key"
                        ),
                        entity_key=channel.key,
                    )
                )
            name = trigger_name(package, channel.key)
            status = await self._plan(
                EntityKind.CHANNEL,
                channel,
                lambda name=name: self._existence.find_trigger(name),
                depends_on=[(EntityKind.AGENT, channel.agent)],
            )
            if status in (EntityStatus.UNCHANGED, EntityStatus.WILL_UPDATE) and channel.bindings:
                if await self._unfinished(channel):
                    self._unfinished_channels.add(channel.key)
                    status = EntityStatus.WILL_UPDATE
                elif channel_credentials(channel, self._values, self._supplied_keys()):
                    status = EntityStatus.WILL_UPDATE
                self._planned[(EntityKind.CHANNEL, channel.key)] = status
            entities.append(
                PreviewEntity(
                    kind=EntityKind.CHANNEL,
                    key=channel.key,
                    name=channel.name,
                    status=status,
                    detail=f"{channel.type}, enabled={channel.enabled}",
                )
            )

    async def _unfinished(self, channel: BundleChannel) -> bool:
        """The channel holds no credentials yet, so a redeploy writes every one it resolves."""
        entity_id = self._ids[(EntityKind.CHANNEL, channel.key)]
        if entity_id is None:
            return True
        stored = await self._existence.channel_credential_keys(entity_id)
        return stored is not None and not (set(channel.bindings) & stored)

    async def _analyze_policies(
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
            # Validate the whole rule against the governance write contract, not
            # just the target selector. The compiler skips anything it cannot
            # read — an unknown target, but equally a cap whose params it cannot
            # interpret — so such a rule installs yet silently never enforces.
            # Block it at analyze-time instead of shipping a false sense of
            # restriction. Bundles reference subjects by key, so the id here is a
            # placeholder: assert_enforceable checks the effect/target/params
            # triple, never the subject id.
            try:
                assert_enforceable(policy_as_rule(policy, _PLACEHOLDER_SUBJECT_ID))
            except ValueError as exc:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=(
                            f"policy '{policy.key}' target '{policy.target}' is invalid "
                            f"({exc}); it would install but never enforce"
                        ),
                        entity_key=policy.key,
                    )
                )
            status = await self._plan(
                EntityKind.POLICY, policy, depends_on=[(EntityKind.AGENT, policy.subject)]
            )
            entities.append(
                PreviewEntity(
                    kind=EntityKind.POLICY,
                    key=policy.key,
                    name=policy.key,
                    status=status,
                    detail=f"{policy.effect} {policy.target} on {policy.subject}",
                )
            )


def required_setup_errors(
    package: Bundle, setup_values: dict[str, Any], needed: set[str] | None = None
) -> list[PreviewIssue]:
    """Block issues for required setup fields missing a value (checked at install).

    ``needed`` narrows the check to the keys a redeploy writes; None checks them all.
    """
    issues: list[PreviewIssue] = []
    for field in package.setup:
        if not field.required or (needed is not None and field.key not in needed):
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


# A YAML error quotes the offending lines; enough to find them, not the whole file.
_MAX_SKILL_ERROR_LENGTH = 300


def skill_content_error(content: str | None) -> str | None:
    """Why SKILL.md content would be refused by the skill service, else None.

    The same parser the skill service creates the skill with, so analyze refuses
    exactly what install would fail on.
    """
    try:
        SkillParser().parse_content(content or "")
    except ValueError as exc:
        message = str(exc).removeprefix("Failed to parse skill content: ")
        message = " ".join(message.split())
        if len(message) > _MAX_SKILL_ERROR_LENGTH:
            message = message[: _MAX_SKILL_ERROR_LENGTH - 3] + "..."
        return f"{message} (check the frontmatter between the '---' lines)"
    return None


def skill_problem(skill: BundleSkill) -> str | None:
    """Why the skill service would refuse this skill's files, else None."""
    if skill.source_type == "content":
        return skill_content_error(skill.content)
    if skill.source_type == "files":
        files = skill.files or {}
        main = skill_main_file(files)
        if main is None or "/" in main:
            return "files must include a SKILL.md at the root"
        return skill_content_error(files[main])
    return None


def context_secret_errors(package: Bundle, setup_values: dict[str, Any]) -> list[PreviewIssue]:
    """Block issues for a context_secret value the MCP service would refuse.

    The message names the field and the rule, never the value.
    """
    from agentarea_mcp.tool_context import CONTEXT_SECRET_MIN_LENGTH

    issues: list[PreviewIssue] = []
    for mcp in package.mcps:
        if mcp.context_secret is None:
            continue
        for key in setup_refs(mcp.context_secret):
            value = setup_values.get(key)
            if value is None or str(value) == "":
                continue  # required_setup_errors reports a missing required value
            if not CONTEXT_SECRET_MIN_LENGTH <= len(str(value)) <= _MAX_CONTEXT_SECRET_LENGTH:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.BLOCK,
                        message=(
                            f"setup field '{key}' is the context_secret of mcp '{mcp.key}' "
                            f"and must be {CONTEXT_SECRET_MIN_LENGTH} to "
                            f"{_MAX_CONTEXT_SECRET_LENGTH} characters long"
                        ),
                        entity_key=key,
                    )
                )
    return issues


# MCPServerInstanceCreate.context_secret caps the length at 512.
_MAX_CONTEXT_SECRET_LENGTH = 512
