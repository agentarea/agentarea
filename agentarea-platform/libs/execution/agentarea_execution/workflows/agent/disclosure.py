"""Progressive disclosure: OpenAPI tool loading, tool sources and skills."""

import json

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_agents_sdk.tools.disclosure import (
        DisclosureContext,
        RevealRequest,
        ToolCandidate,
    )

    from ..helpers import filter_disclosed_tools
    from ..models import Message, ToolCall

from ...models import MaterializeSkillFilesRequest, MaterializeSkillFilesResult
from ..constants import ACTIVITY_TIMEOUT, Activities, EventTypes
from ..retry import make_retry_policy
from .approval import ToolApprovalMixin


class ToolDisclosureMixin(ToolApprovalMixin):
    """Progressive disclosure: OpenAPI tool loading, tool sources and skills."""

    async def _execute_load_openapi_tools(self, tool_call: ToolCall) -> None:
        """Reveal OpenAPI operation schemas by exact name (issue #115 — local).

        Mirrors `_execute_activate_tool_source` for the per-tool, name-based
        case: the LLM picks names from the catalog text already in its prompt
        and asks us to load their schemas. We dict-look up against
        `state.searchable_tool_pool` and append matched schemas (deduped) to
        `state.available_tools`. Names are recorded in
        `state.revealed_openapi_tools` so continue-as-new can replay them.
        """
        try:
            args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}

        requested = args.get("tool_names")
        if not isinstance(requested, list):
            requested = []
        requested = [str(n) for n in requested if n]

        if not self._disclosure_policy or not self.state.searchable_tool_pool:
            self.state.messages.append(
                Message(
                    role="tool",
                    content="Error: no searchable OpenAPI pool available.",
                    tool_call_id=tool_call.id,
                    name="load_tools",
                )
            )
            return

        pool = [ToolCandidate(**c) for c in self.state.searchable_tool_pool]
        context_window = self.state.context_window
        if context_window is None:
            raise ApplicationError(
                "execution state has no ModelSpec context_window",
                type="InvalidExecutionSnapshot",
                non_retryable=True,
            )
        ctx = DisclosureContext(
            model_name=str(self.state.agent_config.get("model_id", "")),
            context_window=context_window,
            iteration=self.state.current_iteration,
        )
        result = self._disclosure_policy.reveal(RevealRequest(tool_names=requested), pool, ctx)

        # Dedup against already-loaded tools by function name.
        existing_names = {
            (t.get("function", {}) or {}).get("name")
            for t in self.state.available_tools
            if t.get("type") == "function"
        }
        for schema in result.revealed:
            name = (schema.get("function", {}) or {}).get("name")
            if name and name not in existing_names:
                self.state.available_tools.append(schema)
                existing_names.add(name)

        revealed_set = set(self.state.revealed_openapi_tools)
        for name in result.matched_names:
            if name not in revealed_set:
                self.state.revealed_openapi_tools.append(name)
                revealed_set.add(name)

        self.state.messages.append(
            Message(
                role="tool",
                content=result.message or f"Loaded {len(result.matched_names)} OpenAPI operations.",
                tool_call_id=tool_call.id,
                name="load_tools",
            )
        )

        self._events.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": "load_tools",
                "tool_call_id": tool_call.id,
                "matched_names": result.matched_names,
                "unknown_names": result.unknown_names,
                "iteration": self.state.current_iteration,
            },
        )

    async def _execute_activate_tool_source(self, tool_call: ToolCall) -> None:
        """Activate a tool source (DYNAMIC mode) — load full definitions into context."""
        try:
            args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}

        source_name = args.get("source_name", "")

        if not self._tool_catalog:
            self.state.messages.append(
                Message(
                    role="tool",
                    content="Error: tool catalog not available (not in dynamic mode).",
                    tool_call_id=tool_call.id,
                    name="activate_tool_source",
                )
            )
            return

        new_tools = filter_disclosed_tools(
            self.state.effective_policy,
            self._tool_catalog.activate(source_name),
            self.state.mcp_tool_routes,
        )
        if new_tools:
            self.state.available_tools.extend(new_tools)
            # Track activated sources for continue-as-new
            activated_sources = getattr(self.state, "activated_tool_sources", []) or []
            if source_name not in activated_sources:
                activated_sources.append(source_name)
                # Store back — ContinueAsNewState carries this
                if hasattr(self.state, "activated_tool_sources"):
                    self.state.activated_tool_sources = activated_sources

            tool_names = [t.get("function", {}).get("name", "?") for t in new_tools]
            result_text = (
                f"Activated '{source_name}' with {len(new_tools)} tools: {', '.join(tool_names)}"
            )
        else:
            result_text = f"Tool source '{source_name}' not found or has no tools."

        self.state.messages.append(
            Message(
                role="tool",
                content=result_text,
                tool_call_id=tool_call.id,
                name="activate_tool_source",
            )
        )

        self._events.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": "activate_tool_source",
                "tool_call_id": tool_call.id,
                "source_name": source_name,
                "tools_loaded": len(new_tools),
                "iteration": self.state.current_iteration,
            },
        )

    async def _execute_skill_activation(self, tool_call: ToolCall) -> None:
        """Execute skill activation locally (no Temporal activity needed)."""
        if not await self._gate_tool_call(tool_call):
            return
        try:
            args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}

        skill_name = args.get("skill_name", "")

        if not self._skill_tool:
            result_text = "No skills available."
        else:
            result = await self._skill_tool.execute(**args)
            result_text = result.get("result", "")

        self.state.messages.append(
            Message(
                role="tool",
                content=result_text,
                tool_call_id=tool_call.id,
                name="activate_skill",
            )
        )

        if skill_name and skill_name not in self.state.activated_skills:
            self.state.activated_skills.append(skill_name)

        # A skill is a folder of files, so activating it puts that folder in the
        # task's sandbox. The workspace persists across shell calls, so one
        # upload is enough and the agent reaches the scripts with plain bash —
        # no second execution tool.
        materialized = await self._materialize_skill_files(skill_name)
        if materialized:
            result_text = f"{result_text}\n\n{materialized}"
            self.state.messages[-1] = Message(
                role="tool",
                content=result_text,
                tool_call_id=tool_call.id,
                name="activate_skill",
            )

        self._events.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": "activate_skill",
                "tool_call_id": tool_call.id,
                "skill_name": skill_name,
                "success": True,
                "result": result_text,
                "iteration": self.state.current_iteration,
            },
        )

    async def _materialize_skill_files(self, skill_name: str) -> str:
        """Copy an activated skill's folder into the sandbox; describe it to the agent.

        Returns a note for the LLM, or an empty string when there is nothing to
        say. Failure to materialize is not fatal: the skill's instructions still
        stand on their own, so the agent keeps working with a degraded skill
        rather than a dead task.
        """
        skill_config = next(
            (s for s in self.state.agent_config.get("skills", []) if s.get("name") == skill_name),
            None,
        )
        skill_id = (skill_config or {}).get("id")
        if not skill_id:
            return ""

        try:
            result = await workflow.execute_activity(
                Activities.MATERIALIZE_SKILL_FILES,
                args=[
                    MaterializeSkillFilesRequest(
                        user_context_data=self.state.user_context_data,
                        skill_id=UUID(skill_id),
                        skill_name=skill_name,
                        workflow_id=workflow.info().workflow_id,
                        workspace_id=str(self.state.workspace_id)
                        if self.state.workspace_id
                        else None,
                        task_id=str(self.state.task_id) if self.state.task_id else None,
                    )
                ],
                result_type=MaterializeSkillFilesResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(2),
            )
        except Exception as e:
            workflow.logger.warning(f"Could not materialize skill '{skill_name}': {e}")
            return ""

        if not result.success:
            workflow.logger.warning(f"Could not materialize skill '{skill_name}': {result.error}")
            return ""

        listing = "\n".join(f"- {path}" for path in result.paths)
        return (
            f"This skill's files are in {result.directory}/ in your sandbox:\n{listing}\n"
            f'Run them with the shell tool, e.g. bash("python {result.directory}/<script>").'
        )
