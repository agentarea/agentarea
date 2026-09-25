"""The request_user_input tool: asking the user and waiting for the answer."""

import asyncio
import json
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from ..models import Message, ToolCall

from ...models import UpdateTaskStatusRequest
from ..constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from ..retry import make_retry_policy
from .approval import ToolApprovalMixin


class UserInputMixin(ToolApprovalMixin):
    """The request_user_input tool: asking the user and waiting for the answer."""

    async def _execute_request_user_input(self, tool_call: ToolCall) -> None:
        """Wait for this request's validated submission, never a generic message."""
        from datetime import timedelta

        if not self._questions_available:
            await self._deny_tool_call(
                tool_call,
                "request_user_input",
                "Questions are unavailable on this route or denied by policy. Continue "
                "autonomously using available context and tools without inventing facts. "
                "Only if an actual prerequisite remains unmet, complete with outcome='blocked'.",
            )
            return

        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}
        if not isinstance(tool_args, dict):
            await self._deny_tool_call(
                tool_call, "request_user_input", "arguments must be an object"
            )
            return
        if self._interaction_contract_enabled and self._pending_input_requests:
            await self._deny_tool_call(
                tool_call, "request_user_input", "A required input request is already pending."
            )
            return

        questions = self._normalize_user_input_questions(tool_args)
        question = str(tool_args.get("question") or "").strip()
        if not question:
            question = questions[0]["question"] if questions else "Please provide input."
        allow_custom_response = bool(tool_args.get("allow_custom_response", True))
        surface_id = tool_args.get("surface_id") if self._interaction_contract_enabled else None
        if surface_id is not None and (
            not isinstance(surface_id, str)
            or not self._a2ui_available
            or surface_id not in self.state.a2ui_surfaces
            or not self.state.a2ui_surfaces[surface_id]
            or any(q["type"] == "secret" for q in questions)
        ):
            await self._deny_tool_call(
                tool_call,
                "request_user_input",
                "surface_id must identify an emitted A2UI surface with an action. "
                "Secret questions must use the native input form without surface_id.",
            )
            return
        input_request_id = str(workflow.uuid4())
        pending_request = {
            "resolved": False,
            "submission": None,
            "questions": questions,
            **(
                {"surface_id": surface_id, "allow_custom_response": allow_custom_response}
                if self._interaction_contract_enabled
                else {}
            ),
        }
        self._pending_input_requests[input_request_id] = pending_request

        self.state.status = ExecutionStatus.WAITING_FOR_INPUT
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[
                UpdateTaskStatusRequest(
                    user_context_data=self.state.user_context_data,
                    task_id=self.state.task_id,
                    status="waiting_for_input",
                    workspace_id=self.state.workspace_id,
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
        )

        self._events.add_event(
            EventTypes.HUMAN_INPUT_REQUESTED,
            {
                "input_request_id": input_request_id,
                "tool_call_id": tool_call.id,
                "iteration": self.state.current_iteration,
                "question": question,
                "questions": questions,
                "allow_custom_response": allow_custom_response,
                "input_mode": "form" if len(questions) > 1 else questions[0]["type"],
                **({"surface_id": surface_id} if surface_id is not None else {}),
            },
        )
        await self._publish_events_immediately()

        try:
            await workflow.wait_condition(
                lambda: pending_request["resolved"],
                timeout=timedelta(minutes=30),
            )
        except TimeoutError:
            self.state.messages.append(
                Message(
                    role="tool",
                    content="No user response was received before the input request timed out.",
                    tool_call_id=tool_call.id,
                    name="request_user_input",
                )
            )
            self._pending_input_requests.pop(input_request_id, None)
            if self._interaction_contract_enabled:
                self.state.success = False
                self.state.status = ExecutionStatus.BLOCKED
                self.state.failure_reason = "input_timeout"
                self.state.blocked_reason = (
                    "Required user input was not received within 30 minutes."
                )
                self.state.error_message = self.state.blocked_reason
                self._awaiting_input = False
            return
        except asyncio.CancelledError:
            self._pending_input_requests.pop(input_request_id, None)
            raise

        submission = pending_request.get("submission") or {}
        if surface_id is not None:
            self.state.a2ui_surfaces.pop(surface_id, None)

        self._events.add_event(
            EventTypes.HUMAN_INPUT_RECEIVED,
            {
                "input_request_id": input_request_id,
                "tool_call_id": tool_call.id,
                "answer_keys": sorted((submission.get("answers") or {}).keys()),
                "secret_keys": sorted((submission.get("secret_refs") or {}).keys()),
                "iteration": self.state.current_iteration,
                **({"surface_id": surface_id} if surface_id is not None else {}),
            },
        )
        await self._publish_events_immediately()

        self.state.status = ExecutionStatus.EXECUTING
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[
                UpdateTaskStatusRequest(
                    user_context_data=self.state.user_context_data,
                    task_id=self.state.task_id,
                    status="running",
                    workspace_id=self.state.workspace_id,
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
        )

        self.state.messages.append(
            Message(
                role="tool",
                content=json.dumps(
                    {
                        "input_request_id": input_request_id,
                        "answers": submission.get("answers") or {},
                        "secret_refs": submission.get("secret_refs") or {},
                    },
                    ensure_ascii=False,
                ),
                tool_call_id=tool_call.id,
                name="request_user_input",
            )
        )
        self._pending_input_requests.pop(input_request_id, None)

    def _normalize_user_input_questions(self, tool_args: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize the simple question/options form and rich questions[] into form fields."""
        raw_questions = tool_args.get("questions")
        if isinstance(raw_questions, list) and raw_questions:
            questions = []
            for idx, raw in enumerate(raw_questions):
                if not isinstance(raw, dict):
                    continue
                field_id = str(raw.get("id") or f"field_{idx + 1}").strip()
                label = str(raw.get("question") or raw.get("label") or field_id).strip()
                field_type = str(raw.get("type") or "text").strip().lower()
                if field_type not in {
                    "text",
                    "textarea",
                    "select",
                    "multiselect",
                    "boolean",
                    "number",
                    "secret",
                }:
                    field_type = "text"
                options = [
                    str(option) for option in (raw.get("options") or []) if str(option).strip()
                ]
                question = {
                    "id": field_id,
                    "question": label,
                    "type": field_type,
                    "required": bool(raw.get("required", True)),
                }
                if options:
                    question["options"] = options
                if field_type == "secret" and raw.get("secret_name"):
                    question["secret_name"] = str(raw["secret_name"])
                questions.append(question)
            if questions:
                return questions

        question = str(tool_args.get("question") or "").strip()
        if not question:
            question = "Please provide the missing information so I can continue."
        raw_options = tool_args.get("options") or []
        options = [str(option) for option in raw_options if str(option).strip()]
        field_type = "select" if options else "text"
        normalized = {
            "id": "answer",
            "question": question,
            "type": field_type,
            "required": True,
        }
        if options:
            normalized["options"] = options
        return [normalized]
