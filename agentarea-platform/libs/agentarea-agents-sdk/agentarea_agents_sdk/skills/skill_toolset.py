"""Skill activation tool for progressive skill disclosure."""

from ..tools.decorator_tool import Toolset, tool_method
from .skill_catalog_builder import SkillEntry


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
        if skill_name in self._activated:
            return f"Skill '{skill_name}' is already active in this session."

        entry = self._skills_registry.get(skill_name)
        if not entry:
            available = ", ".join(self._skills_registry.keys())
            return f"Unknown skill '{skill_name}'. Available: {available}"

        self._activated.add(skill_name)

        result = f'<skill_content name="{skill_name}">\n'
        result += entry.content
        if entry.files:
            result += "\n\nSkill files:\n"
            for f in entry.files:
                result += f"- {f}\n"
        result += "</skill_content>"
        return result

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
