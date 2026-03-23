"""Builds the skill catalog block for agent system prompts."""

from dataclasses import dataclass


@dataclass
class SkillEntry:
    """A skill available for activation."""

    name: str
    description: str
    content: str
    files: list[str]


class SkillCatalogBuilder:
    """Builds the Tier-1 skill catalog for progressive disclosure.

    Produces a compact text block (~50-100 tokens/skill) listing
    available skills by name + description only.
    """

    @staticmethod
    def build_catalog(skills: list[SkillEntry]) -> str:
        """Build catalog text to append to agent instruction.

        Returns empty string if no skills available (don't pollute prompt).
        """
        if not skills:
            return ""

        lines = [
            "\n\n## Available Skills",
            "Skills provide specialized instructions for specific tasks.",
            "When a task matches a skill's description, use the `activate_skill` tool to load its full instructions.\n",
        ]
        for skill in skills:
            desc = skill.description or "No description"
            lines.append(f"- **{skill.name}**: {desc}")

        return "\n".join(lines)

    @staticmethod
    def build_registry(skills: list[SkillEntry]) -> dict[str, SkillEntry]:
        """Build name -> SkillEntry lookup for the activation tool."""
        return {s.name: s for s in skills}
