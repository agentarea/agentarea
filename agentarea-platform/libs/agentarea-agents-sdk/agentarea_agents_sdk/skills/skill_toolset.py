"""Skill activation tool for progressive skill disclosure."""

from ..tools.decorator_tool import Toolset, tool_method
from .skill_catalog_builder import SkillEntry


def wrap_skill_content(skill_name: str, body: str, files: list[str] | None = None) -> str:
    """An activated skill's instructions as the model reads them, and compaction keeps them."""
    result = f'<skill_content name="{skill_name}">\n'
    result += body
    if files:
        result += "\n\nSkill files:\n"
        for f in files:
            result += f"- {f}\n"
    result += "</skill_content>"
    return result


class SkillActivationTool(Toolset):
    """Load full instructions for an available skill. Call this when a task matches a skill's description."""

    def __init__(self, skills_registry: dict[str, SkillEntry]):
        self._skills_registry = skills_registry
        self._activated: set[str] = set()
        super().__init__()

    @property
    def name(self) -> str:
        """Override to use activate_skill as the tool name."""
        return "activate_skill"

    @tool_method
    def activate_skill(self, skill_name: str) -> str:
        """Load full instructions for a skill by name.

        Args:
            skill_name: Name of the skill to activate from the available skills catalog
        """
        refusal = self.refusal(skill_name)
        if refusal is not None:
            return refusal
        return self.render(skill_name, self._skills_registry[skill_name].content)

    def refusal(self, skill_name: str) -> str | None:
        """Why ``skill_name`` cannot be activated now, or ``None`` when it can."""
        if skill_name in self._activated:
            return f"Skill '{skill_name}' is already active in this session."
        if skill_name not in self._skills_registry:
            available = ", ".join(self._skills_registry.keys())
            return f"Unknown skill '{skill_name}'. Available: {available}"
        return None

    def mark_active(self, skill_name: str) -> None:
        """Record ``skill_name`` as active, its instructions delivered by the caller."""
        self._activated.add(skill_name)

    def render(self, skill_name: str, body: str) -> str:
        """Mark ``skill_name`` active and wrap its body for the model."""
        self.mark_active(skill_name)
        return wrap_skill_content(skill_name, body, self._skills_registry[skill_name].files)

    def get_schema(self) -> dict:
        """Override to constrain skill_name to valid enum values."""
        schema = super().get_schema()
        if "parameters" in schema and "properties" in schema["parameters"]:
            skill_names = list(self._skills_registry.keys())
            if "skill_name" in schema["parameters"]["properties"]:
                schema["parameters"]["properties"]["skill_name"]["enum"] = skill_names
        return schema

    @property
    def activated_skills(self) -> set[str]:
        return self._activated.copy()
