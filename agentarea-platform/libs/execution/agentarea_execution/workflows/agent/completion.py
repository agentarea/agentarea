"""The completion tool: validating the answer and its artifacts."""

import json

from temporalio import workflow
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from agentarea_common.money import ZERO

    from ..models import Message, ToolCall

from ...models import (
    ArtifactValidationIssue,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    CapabilityUnavailableResult,
    UpdateTaskStatusRequest,
)
from ..constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from ..retry import make_retry_policy
from .budget import BudgetMixin


class CompletionMixin(BudgetMixin):
    """The completion tool: validating the answer and its artifacts."""

    async def _handle_task_completion(self, completion_call: ToolCall) -> None:
        """Gate completion on code-enforced validation of published artifacts."""
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

        # An explicit completion function call is already present in the
        # conversation as an assistant message. Pair it before the workflow
        # waits for another chat turn; otherwise OpenAI-compatible providers
        # reject the next follow-up because its history contains an unresolved
        # function call. Implicit text completion synthesizes a ToolCall only
        # for local control flow, so it must not gain an orphan tool message.
        call_is_in_history = any(
            call.get("id") == completion_call.id
            for message in self.state.messages
            for call in (message.tool_calls or [])
            if isinstance(call, dict)
        )
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

        # Update task status to completed immediately so UI reflects it
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[
                UpdateTaskStatusRequest(
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
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
        )
        if (
            self._interaction_contract_enabled
            and self.state.interaction_capabilities.channel == "none"
        ):
            self._awaiting_input = False
            return
        self._events.add_event(
            EventTypes.WORKFLOW_AWAITING_FOLLOW_UP,
            {
                "state": "awaiting_follow_up",
                "timeout_seconds": 1800,
                **({"final_response": result_text} if self._interaction_contract_enabled else {}),
            },
        )
        await self._publish_events_immediately()

    def _reject_invalid_completion_arguments(self, completion_call: ToolCall, reason: str) -> None:
        """Return a tool-paired contract error instead of inventing completion data."""
        self.state.success = False
        self.state.final_response = None
        self._awaiting_input = False
        call_is_in_history = any(
            call.get("id") == completion_call.id
            for message in self.state.messages
            for call in (message.tool_calls or [])
            if isinstance(call, dict)
        )
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
            workflow.logger.error("Artifact validation activity failed: %s", exc)
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
        call_is_in_history = any(
            call.get("id") == completion_call.id
            for message in self.state.messages
            for call in (message.tool_calls or [])
            if isinstance(call, dict)
        )
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
