"""ToolCatalog: aggregates ToolProviders for progressive disclosure.

In DYNAMIC mode, only a compact catalog is injected into the system prompt.
The LLM calls activate_tool_source("name") to load full definitions on demand.
"""

from __future__ import annotations

from typing import Any

from .tool_provider import ToolProvider


class ToolCatalog:
    """Aggregates ToolProviders, builds prompt text, handles activation.

    Usage:
        catalog = ToolCatalog(providers, activated={"github"})
        system_prompt += catalog.build_prompt_text()
        tools = catalog.get_activated_tool_definitions()
    """

    def __init__(
        self,
        providers: list[ToolProvider],
        activated: set[str] | None = None,
    ):
        self._providers: dict[str, ToolProvider] = {p.name: p for p in providers}
        self._activated: set[str] = activated or set()

    @property
    def provider_names(self) -> list[str]:
        """All registered provider names."""
        return list(self._providers.keys())

    @property
    def activated_sources(self) -> list[str]:
        """Names of activated sources."""
        return sorted(self._activated)

    def build_prompt_text(self) -> str:
        """Build compact catalog text for the system prompt.

        Example output:
            ## Available Tool Sources
            Use activate_tool_source("name") to enable tools before using them.

            - **github** [mcp] (5 tools): list_repos, create_issue, search_code, ...
            - **analyst** [agent] (3 tools): analyze_data, summarize, recommend
            - **math** [code] (2 tools): calculate, convert_units
        """
        if not self._providers:
            return ""

        inactive = [
            name for name in self._providers
            if name not in self._activated
        ]

        if not inactive:
            return ""  # All sources already activated

        lines = [
            "\n\n## Available Tool Sources",
            'Use activate_tool_source("name") to enable tools before using them.\n',
        ]

        for name in sorted(inactive):
            provider = self._providers[name]
            entry = provider.get_catalog_entry()
            tool_count = len(entry.tool_names)

            # Show first few tool names as preview
            preview_names = entry.tool_names[:5]
            preview = ", ".join(preview_names)
            if tool_count > 5:
                preview += ", ..."

            lines.append(
                f"- **{entry.name}** [{entry.provider_type}] "
                f"({tool_count} tools): {preview}"
            )

        return "\n".join(lines)

    def activate(self, source_name: str) -> list[dict[str, Any]]:
        """Activate a tool source and return its full definitions.

        Returns empty list if source not found (no error — LLM might hallucinate).
        Duplicate activations return tools again (idempotent).
        """
        provider = self._providers.get(source_name)
        if not provider:
            return []

        self._activated.add(source_name)
        return provider.get_tool_definitions()

    def get_activated_tool_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions from activated sources."""
        tools: list[dict[str, Any]] = []
        for name in self._activated:
            provider = self._providers.get(name)
            if provider:
                tools.extend(provider.get_tool_definitions())
        return tools

    def get_activate_tool_source_definition(self) -> dict[str, Any]:
        """OpenAI function definition for the activate_tool_source tool.

        The enum is populated with actual source names so the LLM
        can only request valid sources.
        """
        source_names = sorted(self._providers.keys() - self._activated)

        return {
            "type": "function",
            "function": {
                "name": "activate_tool_source",
                "description": (
                    "Activate a tool source to load its tools into the current session. "
                    "Use this when you need tools from a source listed in Available Tool Sources."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_name": {
                            "type": "string",
                            "description": "Name of the tool source to activate",
                            "enum": source_names if source_names else None,
                        },
                    },
                    "required": ["source_name"],
                },
            },
        }
