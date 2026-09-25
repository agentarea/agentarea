"""One iteration of the agent loop: the model call and its response."""

import json
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from agentarea_agents_sdk.skills import SkillCatalogBuilder
    from agentarea_agents_sdk.tools.disclosure import DisclosureContext, ToolCandidate
    from agentarea_common.money import serialize_money

    from ..helpers import MessageBuilder, ToolCallExtractor
    from ..models import Message, ToolCall

from ...models import LLMCallRequest, LLMCallResult
from ..constants import (
    HEARTBEAT_TIMEOUT,
    LLM_CALL_TIMEOUT,
    LLM_RETRY_ATTEMPTS,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from ..retry import make_retry_policy
from .compaction import CompactionMixin
from .errors import ErrorReportingMixin
from .patches import THINKING_ONLY_REPLY_PATCH
from .tool_dispatch import ToolDispatchMixin


def _render_workspace_attachment_prompt(value: Any) -> str:
    """Render only validated server-generated attachment descriptor fields."""
    if not isinstance(value, list):
        return ""

    lines: list[str] = []
    for descriptor in value[:100]:
        if not isinstance(descriptor, dict):
            continue
        relative_path = descriptor.get("relative_path")
        filename = descriptor.get("filename")
        size = descriptor.get("size")
        content_type = descriptor.get("content_type")
        if not isinstance(relative_path, str) or not relative_path.startswith(
            "inputs/attachments/"
        ):
            continue
        path_parts = relative_path.split("/")
        if (
            len(path_parts) != 3
            or any(part in {"", ".", ".."} for part in path_parts)
            or "\\" in relative_path
            or any(character in relative_path for character in "\r\n\x00")
        ):
            continue
        if not isinstance(filename, str) or filename != path_parts[-1]:
            continue
        if any(character in filename for character in "\r\n\x00"):
            continue
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            continue
        if not isinstance(content_type, str) or any(
            character in content_type for character in "\r\n\x00"
        ):
            content_type = "application/octet-stream"

        lines.append(
            "- path="
            f"{json.dumps(relative_path, ensure_ascii=True)}; "
            f"filename={json.dumps(filename, ensure_ascii=True)}; "
            f"size={size}; content_type={json.dumps(content_type, ensure_ascii=True)}"
        )

    if not lines:
        return ""
    return (
        "\n\nTask attachments are already available in the task workspace. "
        "Use the exact relative paths below and do not ask the user to upload them again:\n"
        + "\n".join(lines)
    )


class LLMTurnMixin(ToolDispatchMixin, CompactionMixin, ErrorReportingMixin):
    """One iteration of the agent loop: the model call and its response."""

    async def _execute_iteration(self) -> None:
        """Execute a single iteration."""
        iteration = self.state.current_iteration

        self._events.add_event(
            EventTypes.ITERATION_STARTED,
            {
                "iteration": iteration,
                "budget_remaining": serialize_money(self._budget.get_remaining()),
            },
        )
        await self._publish_events_immediately()

        try:
            await self._execute_traditional_iteration()

            # Check budget warnings
            await self._check_budget_status()

            self._events.add_event(
                EventTypes.ITERATION_COMPLETED,
                {"iteration": iteration, "total_cost": serialize_money(self._budget.cost)},
            )

            # Emit WorkflowCompleted after IterationCompleted for conversational agents.
            # Stateless runs publish the completion event from _finalize_execution.
            if self._awaiting_input:
                self._events.add_event(
                    EventTypes.WORKFLOW_COMPLETED,
                    {
                        "success": True,
                        "iterations_completed": self.state.current_iteration,
                        "total_cost": serialize_money(self._budget.cost),
                        "result": self.state.final_response,
                        "validation_state": self.state.validation_state,
                        **(
                            {
                                "execution_status": "completed"
                                if self._is_delegation_child()
                                else "waiting"
                            }
                            if self._interaction_contract_enabled
                            else {}
                        ),
                    },
                )
                self._completion_event_published = True

        except Exception as e:
            error_details = self._extract_temporal_error_details(e)
            workflow.logger.error(
                f"Iteration {iteration} failed: {error_details}",
                exc_info=True,
            )
            self._events.add_event(
                EventTypes.LLM_CALL_FAILED,
                {"iteration": iteration, "error": error_details},
            )
            raise

        await self._publish_events_immediately()

    async def _execute_traditional_iteration(self) -> None:
        """Execute iteration using traditional LLM + tool approach."""
        iteration = self.state.current_iteration

        # Build system prompt with agent context and current task
        if self.state.goal:
            # Build instruction with skills appended
            agent_instruction = self.state.agent_config["instruction"]

            # Append skill catalog (progressive disclosure — full content
            # loaded on-demand via the activate_skill tool)
            if self._skill_tool:
                skill_entries = list(self._skill_tool._skills_registry.values())
                catalog_text = SkillCatalogBuilder.build_catalog(skill_entries)
                agent_instruction = agent_instruction + catalog_text

            # Append tool source catalog for progressive disclosure (DYNAMIC mode)
            if self._tool_catalog:
                tool_catalog_text = self._tool_catalog.build_prompt_text()
                if tool_catalog_text:
                    agent_instruction = agent_instruction + tool_catalog_text

            project_id = (self._workflow_metadata or {}).get("project_id")
            if project_id:
                agent_instruction += (
                    "\n\nProject input files are available to shell commands in the "
                    "`inputs/` directory of the sandbox. Use ordinary file operations "
                    "such as `find inputs -maxdepth 2 -type f` to inspect them."
                )

            agent_instruction += _render_workspace_attachment_prompt(
                (self._workflow_metadata or {}).get("workspace_attachments")
            )

            # Append OpenAPI operation catalog (load_mode=searchable, issue #115).
            # Pool lives in workflow state; only this name+description block is
            # sent to the LLM until it explicitly calls load_tools(...).
            if self._disclosure_policy and self.state.searchable_tool_pool:
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
                pool = [ToolCandidate(**c) for c in self.state.searchable_tool_pool]
                openapi_catalog_text = self._disclosure_policy.render_catalog(pool, ctx)
                if openapi_catalog_text:
                    agent_instruction = agent_instruction + openapi_catalog_text

            if self._interaction_contract_enabled:
                agent_instruction += (
                    "\n\nInteraction contract: attempt the task autonomously with available "
                    "context and tools. Do not invent missing facts, credentials, or authorization. "
                    "Unavailable interaction alone does not block useful work. If an actual "
                    "prerequisite remains unmet after available alternatives, call completion "
                    "with outcome='blocked', explain it in result, and declare any artifacts."
                )
                if not self._questions_available:
                    agent_instruction += (
                        "\nQuestions are unavailable for this run. Do not ask the user, "
                        "promise a reply channel, or call request_user_input."
                    )
                if not self.state.interaction_capabilities.allow_approvals:
                    agent_instruction += (
                        "\nHuman approvals cannot be collected on this route. Protected tools "
                        "remain denied; use permitted alternatives, never bypass approval."
                    )
                if self._a2ui_available:
                    agent_instruction += (
                        "\nA2UI presentation alone is informational, not a request for input. "
                        "For required forms, emit the surface and call request_user_input "
                        "with its surface_id and questions in the same turn; do not complete "
                        "until the matching answer arrives. Button action.event.context must "
                        "map question IDs to data-model values. Secret fields MUST use the "
                        "native request_user_input form without surface_id, never A2UI."
                    )

            system_prompt = MessageBuilder.build_system_prompt(
                agent_name=self.state.agent_config.get("name", "AI Agent"),
                agent_instruction=agent_instruction,
                goal_description=self.state.goal.description,
                success_criteria=self.state.goal.success_criteria,
                available_tools=self.state.available_tools,
                a2ui_enabled=self._a2ui_available,
            )

            # Add system message and user message if first iteration
            if iteration == 1:
                # Create messages directly using the Message class
                self.state.messages.append(Message(role="system", content=system_prompt))
                self.state.messages.append(
                    Message(role="user", content=self.state.goal.description)
                )
            # else:
            #     # Add status update for subsequent iterations (not in system prompt)
            #     # Avoid importing PromptBuilder to prevent Temporal sandbox issues
            #     status_msg = f"Iteration {iteration}/{self.state.goal.max_iterations} | Budget remaining: ${self.budget_tracker.get_remaining():.2f}"
            #     # Status updates are just regular user messages in conversation context
            #     self.state.messages.append(
            #         Message(role="user", content=f"Status: {status_msg}")
            #     )

        # Check context window and compact if needed (skip first iteration)
        if self.context_manager and iteration > 1:
            messages_dict_est = [
                {"role": msg.role, "content": msg.content or ""} for msg in self.state.messages
            ]
            estimated = self.context_manager.estimate_usage(messages_dict_est)
            self.context_manager.update_usage(estimated)

            if self.context_manager.needs_compaction():
                await self._compact_context_if_needed()
            elif self.context_manager.should_warn():
                self._events.add_event(
                    EventTypes.CONTEXT_WARNING,
                    {
                        "iteration": self.state.current_iteration,
                        "usage_ratio": self.context_manager.get_usage_ratio(),
                        "message_count": len(self.state.messages),
                    },
                )
                await self._publish_events_immediately()
                self.context_manager.mark_warning_sent()

        # Drain queued A2UI actions as user messages so the LLM can respond
        if self._a2ui_action_queue:
            import json as _json

            for action in self._a2ui_action_queue:
                action_msg = (
                    f"[A2UI Action] The user interacted with the UI surface "
                    f"'{action.get('surface_id', 'unknown')}': "
                    f"action={action.get('name', 'unknown')}, "
                    f"source={action.get('source_component_id', 'unknown')}, "
                    f"context={_json.dumps(action.get('context', {}))}"
                )
                self.state.messages.append(Message(role="user", content=action_msg))
            self._a2ui_action_queue.clear()

        # Drain queued user messages into conversation before calling LLM
        if self._message_queue:
            for msg in self._message_queue:
                self.state.messages.append(Message(role="user", content=msg["content"]))
            self._message_queue.clear()

        # Call LLM
        llm_response = await self._call_llm()

        # Process LLM response
        await self._process_llm_response(llm_response)

    async def _call_llm(self) -> dict[str, Any]:
        """Call LLM with conversation context using Pydantic models."""
        workflow.logger.info(f"Calling LLM in iteration {self.state.current_iteration}")

        # Add event for LLM call start
        self._events.add_event(
            EventTypes.LLM_CALL_STARTED,
            {
                "iteration": self.state.current_iteration,
                "message_count": len(self.state.messages),
            },
        )
        await self._publish_events_immediately()

        try:
            # Convert messages to dict format for LLM call - filter out None values to match agent SDK format
            messages_dict = [
                MessageBuilder.normalize_message_dict(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id,
                        "name": msg.name,
                        "tool_calls": msg.tool_calls,
                    }
                )
                for msg in self.state.messages
            ]

            available_tools = self.state.available_tools
            if not self._questions_available:
                available_tools = [
                    tool
                    for tool in available_tools
                    if (tool.get("function") or {}).get("name") != "request_user_input"
                ]

            # Create Pydantic request model
            llm_request = LLMCallRequest(
                messages=messages_dict,
                model_id=str(self.state.agent_config.get("model_id") or ""),
                tools=available_tools,
                workspace_id=self.state.user_context_data["workspace_id"],
                user_context_data=self.state.user_context_data,
                temperature=None,
                max_tokens=None,
                task_id=self.state.task_id,
                agent_id=self.state.agent_id,
                execution_id=self.state.execution_id,
                iteration=self.state.current_iteration,
                resolved_model=self.state.resolved_model,
                effective_policy=self.state.effective_policy,
                cost_used=self.budget_tracker.cost if self.budget_tracker else None,
                tokens_used=self.state.tokens_used,
                service_cost_used=self.state.service_cost_used,
            )

            response: LLMCallResult = await workflow.execute_activity(
                Activities.CALL_LLM,
                args=[llm_request],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=make_retry_policy(LLM_RETRY_ATTEMPTS),
            )

            # Normalize response fields to support both Pydantic model and plain dict
            if isinstance(response, dict):
                raw_usage = response.get("usage")
                cost_value = response.get("cost", 0.0)
                role_value = response.get("role", "assistant")
                content_value = response.get("content", "")
                thinking_value = response.get("thinking", "")
                tool_calls_value = response.get("tool_calls")
            else:
                raw_usage = getattr(response, "usage", None)
                cost_value = getattr(response, "cost", 0.0)
                role_value = getattr(response, "role", "assistant")
                content_value = getattr(response, "content", "")
                thinking_value = getattr(response, "thinking", "")
                tool_calls_value = getattr(response, "tool_calls", None)

            # Extract usage info and update budget
            if raw_usage is None:
                usage_payload = {}
            else:
                # raw_usage may be a Pydantic model or a plain dict-like object
                try:
                    usage_payload = raw_usage.model_dump()  # Pydantic BaseModel
                except AttributeError:
                    try:
                        if isinstance(raw_usage, dict):
                            usage_payload = raw_usage
                        else:
                            usage_payload = dict(raw_usage.__dict__)
                    except Exception:
                        usage_payload = {}

            usage_info = {
                "cost": cost_value,
                "usage": usage_payload,
            }
            total_tokens = usage_payload.get("total_tokens", 0) if usage_payload else 0
            self._record_inference_usage(
                cost=usage_info["cost"],
                total_tokens=total_tokens,
                source="LLM call",
            )

            # Update context window manager with actual token usage
            if self.context_manager and usage_payload:
                prompt_tokens = usage_payload.get("prompt_tokens", 0)
                if prompt_tokens > 0:
                    self.context_manager.update_usage(prompt_tokens)

            # Strip A2UI JSON from the content sent to frontend via LLM_CALL_COMPLETED
            display_content = content_value
            if self._a2ui_available and content_value:
                from ..a2ui_parser import A2UI_DELIMITER

                if A2UI_DELIMITER in content_value:
                    display_content = content_value.split(A2UI_DELIMITER, 1)[0].rstrip()

            self._events.add_event(
                EventTypes.LLM_CALL_COMPLETED,
                {
                    "iteration": self.state.current_iteration,
                    # Which model produced this. Token counts are meaningless without
                    # it — the same 1000 tokens cost very different amounts depending
                    # on the model, so no consumer can interpret `usage` without it.
                    "model_id": self.state.agent_config.get("model_id"),
                    # The provider's own name for the model, alongside the instance id
                    # above. The id identifies a row; this identifies what was actually
                    # bought, and it survives the row being deleted or recreated —
                    # which a metered fact has to, because it is priced and invoiced
                    # long after the run.
                    "model_name": (self.state.resolved_model or {}).get("model_name"),
                    # Whose credentials paid the provider. Without it there is no way
                    # to tell a run on the operator's key — real money out of our
                    # account, and the only kind that must be recovered from the
                    # customer — from a run on the customer's own, which costs us
                    # nothing and must not be charged for twice.
                    "managed_by": (self.state.resolved_model or {}).get("managed_by"),
                    "cost": usage_info["cost"],
                    "total_cost": serialize_money(self._budget.cost),
                    "usage": usage_info,
                    "content": display_content,
                    "thinking": thinking_value,
                    "tool_calls": tool_calls_value or [],
                    "role": role_value,
                },
            )
            await self._publish_events_immediately()

            # Return dict for compatibility with existing code
            return {
                "role": role_value,
                "content": content_value,
                "tool_call_id": None,  # Not provided by LLM response
                "name": None,  # Not provided by LLM response
                "tool_calls": tool_calls_value,
                "usage": usage_info,
                "cost": cost_value,
            }

        except Exception as e:
            # Simplified error handling - enriched error events are now published by the activity
            error_message = self._extract_temporal_error_details(e)
            error_lower = error_message.lower()

            is_provider_quota_block = (
                "insufficient balance" in error_lower
                or "no resource package" in error_lower
                or "quota exceeded" in error_lower
            )

            # Generic LLM error event for workflow tracking
            user_error = self._get_user_facing_error(e)
            self._events.add_event(
                EventTypes.LLM_CALL_FAILED,
                {
                    "iteration": self.state.current_iteration,
                    "error": user_error,
                    "error_type": self._get_user_facing_error_type(e),
                    "model_id": self.state.agent_config.get("model_id"),
                },
            )

            if is_provider_quota_block:
                self.state.status = ExecutionStatus.BLOCKED
                self.state.blocked_reason = user_error
                self._events.add_event(
                    EventTypes.WORKFLOW_FAILED,
                    {
                        "error": user_error,
                        "error_type": "ProviderQuotaExceeded",
                        "blocked": True,
                        "blocked_reason": user_error,
                        "retryable": False,
                    },
                )

            await self._publish_events_immediately()
            raise

    async def _process_llm_response(self, response: dict[str, Any]) -> None:
        """Process LLM response and handle tool calls."""
        # Only add non-empty messages to state
        content = response.get("content", "")
        tool_calls_raw = response.get("tool_calls")
        thinking_value = response.get("thinking", "")

        # Parse and publish A2UI events if agent has A2UI enabled
        if self._a2ui_available and content:
            from ..a2ui_parser import A2UI_DELIMITER, A2UI_TYPE_TO_CANONICAL, parse_a2ui_response

            if A2UI_DELIMITER in content:
                a2ui_result = parse_a2ui_response(content)
                if a2ui_result.a2ui_events:
                    # Replace content with text-only portion
                    content = a2ui_result.text_content
                    response["content"] = content

                    # Publish each A2UI event through the existing pipeline. The
                    # LLM speaks the A2UI protocol type names; translate to the
                    # canonical dotted vocabulary before emitting.
                    for a2ui_event in a2ui_result.a2ui_events:
                        if self._interaction_contract_enabled:
                            surface_id = a2ui_event["surface_id"]
                            if not isinstance(surface_id, str):
                                continue
                            if a2ui_event["type"] == "A2UICreateSurface":
                                self.state.a2ui_surfaces[surface_id] = {}
                            elif a2ui_event["type"] == "A2UIDeleteSurface":
                                self.state.a2ui_surfaces.pop(surface_id, None)
                            elif a2ui_event["type"] == "A2UIUpdateComponents":
                                actions = self.state.a2ui_surfaces.get(surface_id)
                                if actions is not None:
                                    for component in a2ui_event.get("components") or []:
                                        if not isinstance(component, dict):
                                            continue
                                        component_id = component.get("id")
                                        action = component.get("action") or {}
                                        event = (
                                            action.get("event")
                                            if isinstance(action, dict)
                                            else None
                                        )
                                        name = (
                                            event.get("name") if isinstance(event, dict) else None
                                        )
                                        if isinstance(component_id, str):
                                            if isinstance(name, str) and name:
                                                actions[component_id] = name
                                            else:
                                                actions.pop(component_id, None)
                        event_data = {k: v for k, v in a2ui_event.items() if k != "type"}
                        event_data["task_id"] = str(self.state.task_id)
                        canonical_a2ui = A2UI_TYPE_TO_CANONICAL[a2ui_event["type"]]
                        self._events.add_event(canonical_a2ui, event_data)

                    await self._publish_events_immediately()

                if a2ui_result.parse_error:
                    workflow.logger.warning(f"A2UI parse error: {a2ui_result.parse_error}")

        # Reasoning is not an answer: a reply with only thinking (e.g. GLM cut off
        # before emitting its tool call) is an empty response, never the result.
        effective_content = content
        if not effective_content.strip() and not tool_calls_raw and thinking_value:
            if workflow.patched(THINKING_ONLY_REPLY_PATCH):
                workflow.logger.warning(
                    "LLM returned only reasoning, with no content or tool calls, in "
                    f"iteration {self.state.current_iteration}; treating it as an empty response"
                )
                # Without a new turn the next call repeats the identical prompt and
                # is cut off the same way until the turn budget runs out.
                self.state.messages.append(
                    Message(
                        role="user",
                        content=(
                            "Your previous reply contained only reasoning, with no answer "
                            "and no tool call. Reply with your answer or call a tool."
                        ),
                    )
                )
            else:
                effective_content = thinking_value

        if effective_content.strip() or tool_calls_raw:
            # Create Message directly from response dict
            self.state.messages.append(
                Message(
                    role=response.get("role", "assistant"),
                    content=effective_content,
                    tool_calls=tool_calls_raw,
                )
            )
        else:
            workflow.logger.warning(
                f"Received empty LLM response in iteration {self.state.current_iteration}"
            )

        # Extract and execute tool calls - pass the response dict directly
        tool_calls = ToolCallExtractor.extract_tool_calls(response)

        if tool_calls:
            await self._execute_tool_calls(tool_calls)
        elif effective_content.strip():
            # LLM responded with text but no tool calls.
            # This IS the agent's response — treat it as implicit completion.
            # Most agent frameworks (Claude Code, Cline, OpenCode) work this way:
            # text response = answer to user, no explicit completion tool needed.
            workflow.logger.info("LLM responded with text only — treating as implicit completion")
            completion_call = ToolCall(
                id=str(workflow.uuid4()),
                function={
                    "name": "completion",
                    "arguments": json.dumps({"result": effective_content.strip(), "artifacts": []}),
                },
            )
            await self._handle_task_completion(completion_call)
            return
        else:
            # No content and no tool calls — an empty response. The loop calls the
            # model again; the iteration limit ends a run that never answers.
            workflow.logger.error(
                f"LLM returned empty response with no tool calls in iteration {self.state.current_iteration}"
            )
