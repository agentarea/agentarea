"""Re-export shim: ``SkillsToolset`` now lives in
``agentarea_agents.tools.skills_toolset`` so the worker can register it at
agent runtime. apps/api still assembles it into the MCP platform tools via
``get_platform_tools`` (see ``__init__``), so re-export the class here.
"""

from agentarea_agents.tools.skills_toolset import SkillsToolset

__all__ = ["SkillsToolset"]
