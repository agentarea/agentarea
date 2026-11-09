"""Load an agent folder (relative path -> text) into a canonical :class:`Bundle`.

The folder root is one agent::

    agent.yaml              name, display_name, description, model, toolsets,
                            reasoning_effort | reasoning_max_tokens, client, setup
    instructions.md         the agent instruction
    skills/<key>/           a skill: SKILL.md and any files it ships
    mcp/<key>.yaml          an MCP server, attached to the agent: a catalog id or a spec
    schedules/<key>.md      a cron automation: YAML frontmatter + prompt body
    channels/<key>.yaml     a messaging channel bound to the agent
    policies/<key>.yaml     a governance rule; subject defaults to the agent

Anything else is reported as a WARN issue and ignored. A file that does not
validate raises :class:`BundleParseError` naming that file.
"""

from __future__ import annotations

import re
from typing import Any

import yaml
from agentarea_common.utils.untrusted_yaml import load_untrusted_yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentarea_bundles.application.analyzer import BUNDLE_MAX_NODES, BundleParseError
from agentarea_bundles.schemas.bundle import (
    Bundle,
    BundleAgent,
    BundleAutomation,
    BundleChannel,
    BundleMcp,
    BundlePolicy,
    BundleSkill,
    SetupField,
)
from agentarea_bundles.schemas.preview import IssueSeverity, PreviewIssue

ROOT_AGENT_KEY = "agent"

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(?:---|(.*?)\r?\n---)\r?\n?(.*)\Z", re.DOTALL)
_YAML_SUFFIXES = (".yaml", ".yml")


class _AgentFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    display_name: str | None = None
    description: str = ""
    model: str | None = None
    toolsets: list[str] = Field(default_factory=list)
    reasoning_effort: Any = None
    reasoning_max_tokens: Any = None
    client: str | None = None
    setup: list[SetupField] = Field(default_factory=list)


def check_folder_path(path: str) -> None:
    """Reject anything but a relative POSIX path without empty, '.' or '..' segments."""
    if not path or path.startswith("/") or "\\" in path or re.match(r"^[A-Za-z]:", path):
        raise BundleParseError(f"invalid path '{path}': must be a relative POSIX path")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise BundleParseError(f"invalid path '{path}': empty, '.' or '..' segment")


def _error(path: str, exc: Exception) -> BundleParseError:
    return BundleParseError(f"{path}: {exc}")


def _yaml_mapping(path: str, text: str) -> dict[str, Any]:
    try:
        data = load_untrusted_yaml(text, max_nodes=BUNDLE_MAX_NODES)
    except yaml.YAMLError as exc:
        raise _error(path, exc) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise BundleParseError(f"{path}: must be a mapping at the top level")
    return data


def _frontmatter(path: str, text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text
    return _yaml_mapping(path, match.group(1) or ""), match.group(2)


def _build[T: BaseModel](model: type[T], path: str, data: dict[str, Any]) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise _error(path, exc) from exc


def _stem(name: str) -> str | None:
    for suffix in _YAML_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return None


def load_folder(files: dict[str, str]) -> tuple[Bundle, list[PreviewIssue]]:
    """Build one bundle from an agent folder; unknown entries come back as WARN issues."""
    for path in files:
        check_folder_path(path)
    if "agent.yaml" not in files:
        raise BundleParseError("agent.yaml: missing; the folder root must hold agent.yaml")

    issues: list[PreviewIssue] = []
    skill_files: dict[str, dict[str, str]] = {}
    mcps: list[BundleMcp] = []
    automations: list[BundleAutomation] = []
    channels: list[BundleChannel] = []
    policies: list[BundlePolicy] = []

    def ignore(path: str, why: str) -> None:
        issues.append(
            PreviewIssue(severity=IssueSeverity.WARN, message=f"{path}: {why}; not installed")
        )

    def reserved(path: str, data: dict[str, Any], *names: str) -> None:
        for name in names:
            if name in data:
                issues.append(
                    PreviewIssue(
                        severity=IssueSeverity.WARN,
                        message=f"{path}: '{name}' is set by the folder layout; the value is ignored",
                    )
                )

    for path in sorted(files):
        text = files[path]
        parts = path.split("/")
        top = parts[0]
        if path in ("agent.yaml", "instructions.md"):
            continue
        if top == "skills" and len(parts) >= 3:
            skill_files.setdefault(parts[1], {})["/".join(parts[2:])] = path
        elif top == "mcp" and len(parts) == 2 and (key := _stem(parts[1])) is not None:
            spec = _yaml_mapping(path, text)
            reserved(path, spec, "key")
            mcps.append(_build(BundleMcp, path, {"name": key, **spec, "key": key}))
        elif top == "schedules" and len(parts) == 2 and parts[1].endswith(".md"):
            meta, body = _frontmatter(path, text)
            reserved(path, meta, "key", "agent", "prompt")
            data = {**meta, "key": parts[1][:-3], "agent": ROOT_AGENT_KEY, "prompt": body.strip()}
            automations.append(_build(BundleAutomation, path, data))
        elif top == "channels" and len(parts) == 2 and (key := _stem(parts[1])) is not None:
            spec = _yaml_mapping(path, text)
            reserved(path, spec, "key", "agent")
            data = {"name": key, **spec, "key": key, "agent": ROOT_AGENT_KEY}
            channels.append(_build(BundleChannel, path, data))
        elif top == "policies" and len(parts) == 2 and (key := _stem(parts[1])) is not None:
            spec = _yaml_mapping(path, text)
            reserved(path, spec, "key")
            policies.append(
                _build(BundlePolicy, path, {"subject": ROOT_AGENT_KEY, **spec, "key": key})
            )
        else:
            ignore(path, "not part of the agent folder layout")

    skills: list[BundleSkill] = []
    for key, entries in sorted(skill_files.items()):
        skill_path = f"skills/{key}/SKILL.md"
        if "SKILL.md" not in entries:
            raise BundleParseError(f"{skill_path}: missing; every skill directory needs one")
        content = files[skill_path]
        meta, _ = _frontmatter(skill_path, content)
        name = meta.get("name") if isinstance(meta.get("name"), str) and meta["name"] else key
        data: dict[str, Any] = {"key": key, "name": name}
        if len(entries) == 1:
            data.update(source_type="content", content=content)
        else:
            data.update(
                source_type="files",
                files={rel: files[path] for rel, path in sorted(entries.items())},
            )
        skills.append(_build(BundleSkill, skill_path, data))

    spec = _build(_AgentFile, "agent.yaml", _yaml_mapping("agent.yaml", files["agent.yaml"]))
    try:
        agent = BundleAgent.model_validate(
            {
                "key": ROOT_AGENT_KEY,
                "name": spec.name,
                "description": spec.description,
                "instruction": files.get("instructions.md", ""),
                "model": spec.model,
                "toolsets": spec.toolsets,
                "reasoning_effort": spec.reasoning_effort,
                "reasoning_max_tokens": spec.reasoning_max_tokens,
                "client": spec.client,
                "mcps": [m.key for m in mcps],
                "skills": [s.key for s in skills],
            }
        )
    except ValidationError as exc:
        only_instruction = all(e["loc"][:1] == ("instruction",) for e in exc.errors())
        raise _error("instructions.md" if only_instruction else "agent.yaml", exc) from exc
    bundle = _build(
        Bundle,
        "agent.yaml",
        {
            "name": spec.name,
            "display_name": spec.display_name,
            "description": spec.description,
            "setup": spec.setup,
            "mcps": mcps,
            "skills": skills,
            "agents": [agent],
            "channels": channels,
            "automations": automations,
            "policies": policies,
        },
    )
    return bundle, issues
