"""The completion tool: validating the answer and its artifacts."""

import json

from temporalio import workflow
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from agentarea_common.money import ZERO, serialize_money

    from ..answer_check import (
        accept_rewrite,
        answer_check_config,
        find_leaks,
        rewrite_messages,
        strip_unreadable,
        tool_names_of,
    )
    from ..models import Message, ToolCall

from ...models import (
    ArtifactValidationIssue,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    CapabilityUnavailableResult,
    LLMCallRequest,
    LLMCallResult,
    UpdateTaskStatusRequest,
)
from ..constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    HEARTBEAT_TIMEOUT,
    LLM_CALL_TIMEOUT,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from ..retry import make_retry_policy, model_call_retry_policy
from .budget import BudgetMixin
from .patches import ANSWER_CHECK_REWRITE_PATCH, COMPLETED_STATUS_WITH_TURN_EVENTS_PATCH


class CompletionMixin(BudgetMixin):
    """The completion tool: validating the answer and its artifacts."""

    async def _handle_task_completion(
        self, completion_call: ToolCall, *, answer_checked: bool = False
    ) -> None:
        """Gate completion on code-enforced validation of published artifacts.

        ``answer_checked``: the result is a reply the answer check already saw.
        """
        if self._interaction_contract_enabled and self._pending_input_requests:
            self._reject_invalid_completion_arguments(
                completion_call, "required input is still pending; await its matching submission"
            )
            return
        try:
            tool_args = json.loads(completion_call.function["arguments"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            self._reject_invalid_completion_arguments(
                completion_call, f"arguments must be valid JSON: {exc}"
            )
            return
        if not isinstance(tool_args, dict):
            self._reject_invalid_completion_arguments(
                completion_call, "arguments must be a JSON object"
            )
            return
        result_value = tool_args.get("result")
        if not isinstance(result_value, str) or not result_value.strip():
            self._reject_invalid_completion_arguments(
                completion_call, "result must be a non-empty string"
            )
            return
        if "artifacts" not in tool_args:
            self._reject_invalid_completion_arguments(
                completion_call, "artifacts is required; use [] when the response delivers no files"
            )
            return
        raw_paths = tool_args["artifacts"]
        if not isinstance(raw_paths, list):
            self._reject_invalid_completion_arguments(
                completion_call, "artifacts must be an array of workspace-relative paths"
            )
            return
        if len(raw_paths) > 1000 or any(
            not isinstance(path, str) or not path.strip() for path in raw_paths
        ):
            self._reject_invalid_completion_arguments(
                completion_call,
                "artifacts must contain at most 1000 non-empty workspace-relative paths",
            )
            return
        if len(set(raw_paths)) != len(raw_paths):
            self._reject_invalid_completion_arguments(
                completion_call, "artifacts must not contain duplicates"
            )
            return
        result_text = result_value.strip()
        declared_paths = raw_paths
        outcome = (
            tool_args.get("outcome", "completed")
            if self._interaction_contract_enabled
            else "completed"
        )
        if outcome not in {"completed", "blocked"}:
            self._reject_invalid_completion_arguments(
                completion_call, "outcome must be completed or blocked"
            )
            return

        validation = await self._validate_completion_artifacts(declared_paths)
        if validation.state != "passed":
            self.state.success = False
            self.state.final_response = None
            self._awaiting_input = False
            if validation.state == "unavailable":
                capability = (
                    validation.capability_unavailable.capability
                    if validation.capability_unavailable
                    else "artifact_validator"
                )
                self.state.status = ExecutionStatus.BLOCKED
                self.state.failure_reason = "capability_unavailable"
                self.state.blocked_reason = (
                    f"Artifact validation capability is unavailable: {capability}"
                )
                self.state.error_message = self.state.blocked_reason
                self.state.validation_terminal = True
                return

            if self.state.validation_repair_attempts >= 2:
                self.state.status = ExecutionStatus.FAILED
                self.state.failure_reason = "validation_failed"
                self.state.error_message = "Artifact validation failed after two repair attempts"
                self.state.validation_terminal = True
                return

            self.state.validation_repair_attempts += 1
            self._append_validation_feedback(completion_call, validation)
            return

        if outcome == "completed" and not answer_checked:
            checked = await self._checked_answer(result_text)
            if checked != result_text:
                # The follow-up turns read this reply from the conversation;
                # give them the answer the person saw.
                for message in reversed(self.state.messages):
                    if message.role == "assistant" and (message.content or "").strip() == (
                        result_text
                    ):
                        message.content = checked
                        break
            result_text = checked

        # An explicit completion function call is already present in the
        # conversation as an assistant message. Pair it before the workflow
        # waits for another chat turn; otherwise OpenAI-compatible providers
        # reject the next follow-up because its history contains an unresolved
        # function call. Implicit text completion synthesizes a ToolCall only
        # for local control flow, so it must not gain an orphan tool message.
        call_is_in_history = self._call_in_history(completion_call.id)
        if call_is_in_history:
            self.state.messages.append(
                Message(
                    role="tool",
                    name="completion",
                    tool_call_id=completion_call.id,
                    content=json.dumps(
                        {
                            "status": outcome,
                            "result": result_text,
                            "artifacts": declared_paths,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
        if outcome == "blocked":
            self.state.success = False
            self.state.status = ExecutionStatus.BLOCKED
            self.state.failure_reason = "unmet_prerequisite"
            self.state.blocked_reason = result_text
            self.state.error_message = result_text
            self.state.final_response = result_text
            self._awaiting_input = False
            return

        self.state.success = True
        self.state.final_response = result_text
        self.state.status = ExecutionStatus.COMPLETED
        self.state.failure_reason = None
        self.state.error_message = None
        self.state.blocked_reason = None
        self.state.validation_terminal = False
        # Every agent stays alive after completing a turn to accept follow-up
        # messages (the chat is conversational). Delegation children are the
        # only exception — that is handled in the main loop via
        # _is_delegation_child(), not here.
        self._awaiting_input = True

        workflow.logger.info(f"Task completed: {result_text}")
        workflow.logger.info("Entering awaiting_input state for follow-up messages")

        completed = UpdateTaskStatusRequest(
            user_context_data=self.state.user_context_data,
            task_id=self.state.task_id,
            status="completed",
            result=json.dumps(
                {
                    "response": result_text,
                    "artifacts": [evidence.path for evidence in validation.evidence],
                    "validation_state": self.state.validation_state,
                }
            ),
            workspace_id=self.state.workspace_id,
            total_cost=self.budget_tracker.cost if self.budget_tracker else ZERO,
            own_cost=self._own_cost,
            tokens_used=self.state.tokens_used,
        )
        if self._task_log_on() and workflow.patched(COMPLETED_STATUS_WITH_TURN_EVENTS_PATCH):
            # Stored when the turn ends, in one record with its closing events.
            self._completed_status = completed
        else:
            await self._persist_task_status(completed)
        window = self._follow_up_window()
        if window is None:
            self._awaiting_input = False
            return
        self._events.add_event(
            EventTypes.WORKFLOW_AWAITING_FOLLOW_UP,
            {
                "state": "awaiting_follow_up",
                "timeout_seconds": int(window.total_seconds()),
                **({"final_response": result_text} if self._interaction_contract_enabled else {}),
            },
        )
        await self._publish_events_immediately()

    def _answer_check(self) -> dict | None:
        """The run's answer check: a governance rule's, else the agent's own, or None."""
        return answer_check_config(
            self.state.effective_policy, self.state.agent_config.get("answer_check")
        )

    async def _checked_answer(self, text: str) -> str:
        """The final answer after the answer check: as is, rewritten once, or stripped.

        Off unless ``_answer_check`` is on. The rewrite is a silent call to the
        agent's own model (no chunks, no conversation write). Its
        ``llm.call.completed`` (``purpose: answer_check``) meters it and carries
        the answer the person sees; ``answer.checked`` records what was found and
        the model's account of what it changed. A failed or unusable rewrite
        keeps the original, minus CJK characters when those were the leak.
        """
        config = self._answer_check()
        if config is None:
            return text
        language = config.get("language")
        leaks = find_leaks(text, tool_names_of(self.state.available_tools), language)
        if not leaks or not workflow.patched(ANSWER_CHECK_REWRITE_PATCH):
            return text

        strip_cjk = any(leak.kind == "cjk" for leak in leaks)
        checked = strip_unreadable(text) if strip_cjk else text
        rewrite = None
        try:
            response: LLMCallResult = await workflow.execute_activity(
                Activities.CALL_LLM,
                args=[
                    LLMCallRequest(
                        messages=rewrite_messages(
                            text, leaks, language, config.get("rewrite_instruction")
                        ),
                        model_id=str(self.state.agent_config.get("model_id") or ""),
                        tools=None,
                        workspace_id=self.state.user_context_data["workspace_id"],
                        user_context_data=self.state.user_context_data,
                        temperature=0,
                        max_tokens=4000,
                        agent_id=self.state.agent_id,
                        execution_id=self.state.execution_id,
                        resolved_model=self.state.resolved_model,
                        effective_policy=self.state.effective_policy,
                        cost_used=self.budget_tracker.cost if self.budget_tracker else None,
                        tokens_used=self.state.tokens_used,
                        service_cost_used=self.state.service_cost_used,
                    )
                ],
                result_type=LLMCallResult,
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=model_call_retry_policy(),
            )
            usage = response.usage.model_dump() if response.usage else {}
            self._account_inference_usage(
                cost=response.cost,
                total_tokens=usage.get("total_tokens", 0),
                source="answer check",
            )
            rewrite = accept_rewrite(text, response.content, strip_cjk=strip_cjk)
            if rewrite is None:
                workflow.logger.warning("Answer check rewrite was unusable, keeping the answer")
            else:
                checked = rewrite.answer
            self._events.add_event(
                EventTypes.LLM_CALL_COMPLETED,
                {
                    "iteration": self.state.current_iteration,
                    "purpose": "answer_check",
                    "model_id": self.state.agent_config.get("model_id"),
                    "model_name": (self.state.resolved_model or {}).get("model_name"),
                    "managed_by": (self.state.resolved_model or {}).get("managed_by"),
                    "cost": serialize_money(response.cost),
                    "provider_cost_usd": (
                        serialize_money(response.provider_cost_usd)
                        if response.provider_cost_usd is not None
                        else None
                    ),
                    "total_cost": serialize_money(self._budget.cost),
                    "usage": {"cost": serialize_money(response.cost), "usage": usage},
                    "content": checked,
                    "thinking": "",
                    "tool_calls": [],
                    "role": "assistant",
                },
            )
        except ActivityError as exc:
            workflow.logger.warning(f"Answer check rewrite failed, keeping the answer: {exc}")

        self._events.add_event(
            EventTypes.ANSWER_CHECKED,
            {
                "iteration": self.state.current_iteration,
                "leaks": [leak.as_dict() for leak in leaks],
                "rewritten": rewrite is not None,
                "changes": rewrite.changes if rewrite else None,
            },
        )
        await self._publish_events_immediately()
        return checked

    def _reject_invalid_completion_arguments(self, completion_call: ToolCall, reason: str) -> None:
        """Return a tool-paired contract error instead of inventing completion data."""
        self.state.success = False
        self.state.final_response = None
        self._awaiting_input = False
        call_is_in_history = self._call_in_history(completion_call.id)
        if not call_is_in_history:
            self.state.messages.append(
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {
                            "id": completion_call.id,
                            "type": "function",
                            "function": completion_call.function,
                        }
                    ],
                )
            )
        self.state.messages.append(
            Message(
                role="tool",
                name="completion",
                tool_call_id=completion_call.id,
                content=json.dumps(
                    {
                        "status": "invalid_completion_arguments",
                        "error": reason,
                        "instruction": (
                            "Call completion again with a non-empty result and an explicit "
                            "artifacts array of workspace-relative paths. Use [] only when the "
                            "response delivers no files."
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )

    async def _validate_completion_artifacts(
        self, declared_paths: list[str]
    ) -> ArtifactValidationResult:
        """Persist the files the completion delivers and record the audit events."""
        self.state.validation_state = "running"
        self._events.add_event(
            EventTypes.VALIDATION_STARTED,
            {
                "validation_state": "running",
                "repair_attempt": self.state.validation_repair_attempts,
                "declared_artifact_count": len(declared_paths),
            },
        )
        await self._publish_events_immediately()

        try:
            result = await workflow.execute_activity(
                Activities.VALIDATE_ARTIFACTS,
                args=[
                    ArtifactValidationRequest(
                        user_context_data=self.state.user_context_data,
                        workspace_id=self.state.workspace_id,
                        task_id=self.state.task_id,
                        workflow_id=self.state.execution_id,
                        declared_paths=declared_paths,
                    )
                ],
                result_type=ArtifactValidationResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
            )
            if isinstance(result, dict):
                result = ArtifactValidationResult.model_validate(result)
        except ActivityError as exc:
            if self._is_cancellation(exc):
                raise
            workflow.logger.error("Artifact validation activity failed: %s", exc, exc_info=True)
            result = ArtifactValidationResult(
                state="unavailable",
                generation=0,
                capability_unavailable=CapabilityUnavailableResult(capability="artifact_validator"),
                issues=[
                    ArtifactValidationIssue(
                        path="",
                        validator="artifact_validator",
                        code="capability_unavailable",
                        message="Artifact validation activity could not run",
                    )
                ],
            )

        self.state.validation_state = result.state
        self._events.add_event(
            EventTypes.VALIDATION_COMPLETED,
            {
                "validation_state": result.state,
                "generation": result.generation,
                "repair_attempt": self.state.validation_repair_attempts,
                "evidence": [item.model_dump() for item in result.evidence],
                "issues": [item.model_dump() for item in result.issues],
                "capability_unavailable": result.capability_unavailable.model_dump()
                if result.capability_unavailable
                else None,
            },
        )
        await self._publish_events_immediately()
        return result

    def _append_validation_feedback(
        self,
        completion_call: ToolCall,
        result: ArtifactValidationResult,
    ) -> None:
        """Return structured, tool-paired repair evidence to the next model turn."""
        call_is_in_history = self._call_in_history(completion_call.id)
        if not call_is_in_history:
            self.state.messages.append(
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {
                            "id": completion_call.id,
                            "type": "function",
                            "function": completion_call.function,
                        }
                    ],
                )
            )

        feedback = {
            "status": "validation_failed",
            "validation_state": result.state,
            "repair_attempt": self.state.validation_repair_attempts,
            "repair_attempts_remaining": 2 - self.state.validation_repair_attempts,
            "generation": result.generation,
            "issues": [item.model_dump() for item in result.issues],
            "instruction": (
                "Repair or create the missing output in the workspace, then call completion "
                "again with the workspace-relative paths in artifacts. Do not claim success "
                "until validation passes."
            ),
        }
        self.state.messages.append(
            Message(
                role="tool",
                name="completion",
                tool_call_id=completion_call.id,
                content=json.dumps(feedback, ensure_ascii=False, separators=(",", ":")),
            )
        )
