"""What an agent revision fixes: the fields the runtime acts on, and nothing else.

Identity (name, slug, description) and governance (policies, grants, budgets,
triggers) stay on the agent. A revision changes behaviour; it never carries
authority.
"""

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from agentarea_agents.domain.config_hash import compute_agent_config_hash

SPEC_FIELDS = ("instruction", "model_id", "tools", "skill_ids", "planning", "a2ui_enabled")


def _tool_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _tool_key(tool: dict[str, Any]) -> str:
    return json.dumps(tool, sort_keys=True)


@dataclass(frozen=True)
class RevisionSpec:
    instruction: str | None
    model_id: str | None
    tools: list[dict[str, Any]] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)
    planning: bool | None = None
    a2ui_enabled: bool | None = None

    def __post_init__(self) -> None:
        """Normalize so equal configs compare and hash equal."""
        object.__setattr__(self, "tools", _tool_list(self.tools))
        object.__setattr__(self, "skill_ids", sorted(str(s) for s in self.skill_ids))

    @classmethod
    def from_agent(cls, agent: Any, skill_ids: list[str]) -> "RevisionSpec":
        return cls(
            instruction=agent.instruction,
            model_id=agent.model_id,
            tools=_tool_list(agent.tools),
            skill_ids=list(skill_ids),
            planning=agent.planning,
            a2ui_enabled=agent.a2ui_enabled,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RevisionSpec":
        return cls(
            instruction=data.get("instruction"),
            model_id=data.get("model_id"),
            tools=_tool_list(data.get("tools")),
            skill_ids=[str(s) for s in data.get("skill_ids") or []],
            planning=data.get("planning"),
            a2ui_enabled=data.get("a2ui_enabled"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        return compute_agent_config_hash(self.to_dict(), skill_ids=self.skill_ids)

    def expands_capability_of(self, base: "RevisionSpec") -> bool:
        """Whether adopting this spec over ``base`` lets the agent do more.

        Composition is the allow in the runtime PDP, so an added tool or skill,
        a different model, or turning planning on widens what the agent may do.
        """
        base_tools = {_tool_key(t) for t in base.tools}
        if any(_tool_key(t) not in base_tools for t in self.tools):
            return True
        if not set(self.skill_ids) <= set(base.skill_ids):
            return True
        if self.model_id != base.model_id:
            return True
        return bool(self.planning) and not bool(base.planning)


def apply_patch(base: RevisionSpec, patch: dict[str, Any]) -> RevisionSpec:
    unknown = sorted(set(patch) - set(SPEC_FIELDS))
    if unknown:
        raise ValueError(f"not revision fields: {', '.join(unknown)}")
    return replace(base, **patch)


def diff_specs(before: RevisionSpec, after: RevisionSpec) -> list[dict[str, Any]]:
    a, b = before.to_dict(), after.to_dict()
    return [
        {"field": name, "before": a[name], "after": b[name]}
        for name in SPEC_FIELDS
        if a[name] != b[name]
    ]
