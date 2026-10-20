"""Progressive disclosure: OpenAPI tool loading, tool sources and skills."""

import json

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_agents_sdk.tools.disclosure import (
        DisclosureContext,
        RevealRequest,
        ToolCandidate,
    )

    from ..helpers import filter_disclosed_tools
    from ..models import Message, ToolCall

from ...models import (
    ActivateSkillRequest,
    ActivateSkillResult,
    MaterializeSkillFilesRequest,
    MaterializeSkillFilesResult,
)
from ..constants import (
    ACTIVITY_TIMEOUT,
    HEARTBEAT_TIMEOUT,
    LEGACY_SKILLS_WINDOW_SHARE,
    SKILL_CONTEXT_SHARE,
    SKILL_MIN_TOKENS,
    Activities,
    EventTypes,
)
from ..helpers import SEEN_URLS_LIMIT
from ..retry import make_retry_policy
from .approval import ToolApprovalMixin
from .outage import OutageWaitMixin, failure_text
from .patches import SKILL_BODY_ON_ACTIVATION_PATCH


class ToolDisclosureMixin(ToolApprovalMixin, OutageWaitMixin):
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
        except json.JSONDecodeError, KeyError:
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
        except json.JSONDecodeError, KeyError:
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
            *self._policy_tool_configs(),
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
        """Activate a skill: hand the model its instructions and put its files in the sandbox."""
        allowed, _ = await self._gate_tool_call(tool_call)
        if not allowed:
            return
        try:
            args = json.loads(tool_call.function["arguments"])
        except json.JSONDecodeError, KeyError:
            args = {}

        skill_name = args.get("skill_name", "")

        if (
            self._skill_tool
            and self._task_log_on()
            and workflow.patched(SKILL_BODY_ON_ACTIVATION_PATCH)
        ):
            refusal = self._skill_tool.refusal(skill_name)
            if refusal is None:
                await self._activate_skill_from_package(tool_call, skill_name)
                return
            self._answer_skill_activation(tool_call, skill_name, refusal, success=True)
            return

        if not self._skill_tool:
            result_text = "No skills available."
        else:
            result = await self._skill_tool.execute(**args)
            result_text = result.get("result", "")

        skill_result = Message(
            role="tool",
            content=result_text,
            tool_call_id=tool_call.id,
            name="activate_skill",
        )
        self.state.messages.append(skill_result)

        if skill_name and skill_name not in self.state.activated_skills:
            self.state.activated_skills.append(skill_name)

        # A skill is a folder of files, so activating it puts that folder in the
        # task's sandbox. The workspace persists across shell calls, so one
        # upload is enough and the agent reaches the scripts with plain bash —
        # no second execution tool.
        materialized = await self._materialize_skill_files(skill_name)
        if materialized:
            result_text = f"{result_text}\n\n{materialized}"
            # A signal handled meanwhile may have added a row after the result.
            skill_result.content = result_text

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

    async def _activate_skill_from_package(self, tool_call: ToolCall, skill_name: str) -> None:
        """Activate a skill through its activity; its SKILL.md never enters workflow history.

        The rows pending so far are recorded first, so the activity writes the
        skill's entry at the next position of the log; the run then only moves
        its cursor past it. The entry fits the share of the window one skill
        may take and what the run's skills together have left. A storage
        outage is waited out; a refusal or a skill gone is the model's tool
        error, naming the skill, written at the same position.
        """
        skill_config = next(
            s for s in self.state.agent_config.get("skills", []) if s.get("name") == skill_name
        )
        context_window = self.state.context_window or int(
            self.state.agent_config.get("context_window") or 0
        )
        share = self.state.agent_config.get("skills_window_share") or LEGACY_SKILLS_WINDOW_SHARE
        left = int(context_window * share) - self.state.skill_tokens_used
        max_tokens = min(int(context_window * SKILL_CONTEXT_SHARE), left)
        if max_tokens < SKILL_MIN_TOKENS:
            refusal = (
                f"Skill '{skill_name}' was not loaded: the skills already active take the "
                f"{share:.0%} of the context window this run's skills may use."
            )
            self._answer_skill_activation(tool_call, skill_name, refusal, success=False)
            return

        await self._record()
        seq = self.state.conversation_next_seq
        self.state.conversation_next_seq += 1
        event_id = str(workflow.uuid4())
        request = ActivateSkillRequest(
            skill_id=UUID(skill_config["id"]),
            skill_name=skill_name,
            user_context_data=self.state.user_context_data,
            workspace_id=str(self.state.workspace_id),
            task_id=str(self.state.task_id),
            workflow_id=workflow.info().workflow_id,
            execution_id=self.state.execution_id,
            tool_call_id=tool_call.id,
            seq=seq,
            event_id=event_id,
            iteration=self.state.current_iteration,
            max_tokens=max_tokens,
            package=skill_config.get("package"),
        )
        try:
            result = await self._execute_through_outage(
                Activities.ACTIVATE_SKILL,
                request,
                ActivateSkillResult,
                what=f"activating skill '{skill_name}'",
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
            )
        except ActivityError as e:
            if self._is_cancellation(e):
                raise
            error = failure_text(e)
            workflow.logger.warning(f"Could not activate skill '{skill_name}': {error}")
            await self._record_at(
                seq,
                event_id,
                Message(
                    role="tool",
                    content=f"Tool failed: {error}",
                    tool_call_id=tool_call.id,
                    name="activate_skill",
                ),
            )
            self._events.add_event(
                EventTypes.TOOL_CALL_FAILED,
                {
                    "tool_name": "activate_skill",
                    "tool_call_id": tool_call.id,
                    "skill_name": skill_name,
                    "success": False,
                    "error": error,
                    "iteration": self.state.current_iteration,
                },
            )
            return

        if self._skill_tool:
            self._skill_tool.mark_active(skill_name)
        if skill_name not in self.state.activated_skills:
            self.state.activated_skills.append(skill_name)
        self._recorded_turn_answered.add(tool_call.id)
        self.state.skill_tokens_used += result.est_tokens
        # The entry is in the log, not pending: the next call's prompt holds it on
        # top of the last one, which is what the pre-call estimate starts from.
        self.state.last_prompt_tokens += result.est_tokens
        known = set(self.state.seen_urls)
        self.state.seen_urls.extend(url for url in result.urls if url not in known)
        del self.state.seen_urls[:-SEEN_URLS_LIMIT]
        self._events.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": "activate_skill",
                "tool_call_id": tool_call.id,
                "skill_name": skill_name,
                "success": True,
                "result": f"Loaded skill '{skill_name}' ({result.chars} characters)",
                "summarized": result.summarized,
                "iteration": self.state.current_iteration,
            },
        )

    def _answer_skill_activation(
        self, tool_call: ToolCall, skill_name: str, text: str, *, success: bool
    ) -> None:
        self.state.messages.append(
            Message(role="tool", content=text, tool_call_id=tool_call.id, name="activate_skill")
        )
        self._events.add_event(
            EventTypes.TOOL_CALL_COMPLETED if success else EventTypes.TOOL_CALL_FAILED,
            {
                "tool_name": "activate_skill",
                "tool_call_id": tool_call.id,
                "skill_name": skill_name,
                "success": success,
                ("result" if success else "error"): text,
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
            if self._is_cancellation(e):
                raise
            workflow.logger.warning(
                f"Could not materialize skill '{skill_name}': {e}", exc_info=True
            )
            return ""

        if not result.success:
            workflow.logger.warning(f"Could not materialize skill '{skill_name}': {result.error}")
            return ""

        listing = "\n".join(f"- {path}" for path in result.paths)
        return (
            f"This skill's files are in {result.directory}/ in your sandbox:\n{listing}\n"
            f'Run them with the shell tool, e.g. bash("python {result.directory}/<script>").'
        )
