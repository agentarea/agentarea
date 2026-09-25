"""Mid-run commands: model and budget changes, continuation, queued messages and input."""

from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from agentarea_common.money import ZERO, serialize_money, to_money
    from agentarea_governance.domain.policies import effective_policy_from_json

    from ..context_manager import ContextWindowManager

from ...models import BudgetUpdatePayload, ChangeModelPayload, ContinueExecutionPayload
from ..constants import EventTypes, ExecutionStatus
from .budget import BudgetMixin


class CommandsMixin(BudgetMixin):
    """Mid-run commands: model and budget changes, continuation, queued messages and input."""

    def _handle_change_model(self, payload: dict[str, Any]) -> None:
        """Handle a change_model command: update cached model info and agent config."""
        info = ChangeModelPayload(**payload)
        old = self.state.resolved_model
        self.state.resolved_model = info.model_dump()
        self.state.agent_config["model_id"] = info.model_id
        if info.context_window != self.state.context_window:
            self.state.context_window = info.context_window
            if self.context_manager:
                self.context_manager = ContextWindowManager(info.context_window)
        if self.event_manager:
            self.event_manager.add_event(
                EventTypes.MODEL_CHANGED,
                {
                    "old_model": old.get("model_name") if old else None,
                    "new_model": info.model_name,
                    "new_model_id": info.model_id,
                },
            )
        workflow.logger.info(
            f"Model changed: {old.get('model_name') if old else 'none'} -> {info.model_name}"
        )

    def _handle_update_budget(self, payload: dict[str, Any]) -> None:
        """Allow only a tighter budget without a governance re-resolution."""
        info = BudgetUpdatePayload(**payload)
        if info.budget_usd < self._budget.cost:
            raise ValueError("budget_usd cannot be lower than accumulated cost")
        policy_budget = ((self.state.effective_policy or {}).get("budget") or {}).get(
            "run_budget_usd"
        )
        if policy_budget is None:
            raise ValueError("effective policy is missing budget.run_budget_usd")
        if info.budget_usd > to_money(policy_budget):
            raise ValueError("budget increases require a re-resolved governance snapshot")
        old_limit = self._budget.budget_limit
        self._budget.set_limit(info.budget_usd)
        self.state.budget_usd = self._budget.budget_limit
        if self.event_manager:
            self.event_manager.add_event(
                "BudgetUpdated",
                {
                    "old_limit": serialize_money(old_limit),
                    "new_limit": serialize_money(self._budget.budget_limit),
                },
            )

    def _prepare_continuation(
        self,
        payload: dict[str, Any],
    ) -> tuple[ContinueExecutionPayload | None, dict[str, Any] | None]:
        """Validate a policy revision without mutating workflow state."""
        info = ContinueExecutionPayload(**payload)
        if not self._waiting_for_continuation:
            return None, {"accepted": False, "reason": "not_waiting_for_continuation"}
        if info.additional_iterations == 0 and info.additional_budget_usd is None:
            return None, {"accepted": False, "reason": "no_resources_granted"}
        if (
            self._continuation_failure_reason == "iteration_limit"
            and info.additional_iterations == 0
        ):
            return None, {
                "accepted": False,
                "reason": "additional_iterations_required",
            }
        if (
            self._continuation_failure_reason == "budget_exceeded"
            and info.additional_budget_usd is None
        ):
            return None, {"accepted": False, "reason": "additional_budget_required"}
        if self.state.goal is None:
            return None, {"accepted": False, "reason": "goal_not_initialized"}
        if info.effective_policy is None or info.governance_snapshot is None:
            return None, {
                "accepted": False,
                "reason": "governance_snapshot_required",
            }

        try:
            current_policy = effective_policy_from_json(self.state.effective_policy)
            next_policy = effective_policy_from_json(info.effective_policy)
            current_policy.runtime_contract()
            next_runtime = next_policy.runtime_contract()
        except (TypeError, ValueError):
            return None, {"accepted": False, "reason": "invalid_governance_snapshot"}

        if info.governance_snapshot.get("effective_policy") != next_policy.to_json_dict():
            return None, {"accepted": False, "reason": "invalid_governance_snapshot"}
        revision = info.governance_snapshot.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 2:
            return None, {"accepted": False, "reason": "invalid_governance_snapshot"}

        expected_iterations = self.state.goal.max_iterations + info.additional_iterations
        if next_runtime.max_model_turns != expected_iterations:
            return None, {"accepted": False, "reason": "policy_revision_mismatch"}
        expected_budget = self._budget.budget_limit + (info.additional_budget_usd or ZERO)
        if next_runtime.run_budget_usd != expected_budget:
            return None, {"accepted": False, "reason": "policy_revision_mismatch"}

        current_contract = current_policy.to_json_dict()
        next_contract = next_policy.to_json_dict()
        for contract in (current_contract, next_contract):
            contract.pop("source_policy_ids", None)
            contract.pop("resolver_version", None)
            contract["budget"].pop("run_budget_usd", None)
            contract["execution"].pop("max_model_turns", None)
        if next_contract != current_contract:
            return None, {
                "accepted": False,
                "reason": "unexpected_policy_dimension_change",
            }
        return info, None

    def _commit_continuation(
        self,
        info: ContinueExecutionPayload,
    ) -> dict[str, Any]:
        """Commit a policy revision after its task snapshot is durable."""
        next_policy = effective_policy_from_json(info.effective_policy)
        next_runtime = next_policy.runtime_contract()
        if self.state.goal is None:
            raise RuntimeError("goal is not initialized")

        self.state.goal = self.state.goal.model_copy(
            update={"max_iterations": next_runtime.max_model_turns}
        )
        self._budget.set_limit(next_runtime.run_budget_usd)
        self.state.budget_usd = self._budget.budget_limit
        self.state.effective_policy = next_policy.to_json_dict()

        self._continuation_count += 1
        self._waiting_for_continuation = False
        self.state.status = ExecutionStatus.EXECUTING
        self.state.failure_reason = None
        self.state.error_message = None
        return {
            "accepted": True,
            "continuation_count": self._continuation_count,
            "max_iterations": self.state.goal.max_iterations if self.state.goal else None,
            "budget_usd": serialize_money(self._budget.budget_limit),
        }

    def _apply_continuation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and commit a continuation for deterministic unit use."""
        info, rejection = self._prepare_continuation(payload)
        if rejection is not None:
            return rejection
        if info is None:
            raise RuntimeError("continuation validation returned no result")
        return self._commit_continuation(info)

    def _handle_continue_execution(self, payload: dict[str, Any]) -> None:
        """Reject the legacy signal path, which cannot persist a policy revision."""
        workflow.logger.warning(
            "continue_execution signal ignored; use the validated workflow update"
        )

    def _handle_queue_message(self, payload: dict[str, Any]) -> None:
        """Queue a user message for the agent's next iteration."""
        msg_id = str(workflow.uuid4())
        # Accept both "message" and "content" keys for robustness
        text = payload.get("message") or payload.get("content") or ""
        if not isinstance(text, str):
            raise ValueError("message must be a string")
        if not text:
            workflow.logger.warning("queue_message received with empty text, ignoring")
            return
        self._message_queue.append({"id": msg_id, "content": text})
        if self.event_manager:
            self.event_manager.add_event(
                "MessageQueued",
                {
                    "message_id": msg_id,
                    "content_length": len(text),
                },
            )
        workflow.logger.info(f"Message queued: {msg_id}")

    def _handle_submit_user_input(self, payload: dict[str, Any]) -> None:
        """Resolve a pending structured user-input request."""
        input_request_id = str(payload.get("input_request_id") or "")
        pending = self._pending_input_requests.get(input_request_id)
        if not pending:
            workflow.logger.warning(
                f"submit_user_input ignored for unknown input_request_id={input_request_id!r}"
            )
            return

        if pending.get("resolved"):
            return
        answers = payload.get("answers") or {}
        secret_refs = payload.get("secret_refs") or {}
        if self._interaction_contract_enabled:
            if not isinstance(answers, dict) or not isinstance(secret_refs, dict):
                return
            questions = pending.get("questions") or []
            fields = {q["id"]: q for q in questions}
            if answers.keys() - fields.keys() or secret_refs.keys() - fields.keys():
                return
            for field_id, field in fields.items():
                if field.get("type") == "secret":
                    if field_id in answers:
                        return
                    ref = secret_refs.get(field_id)
                    if ref is not None and (
                        not isinstance(ref, dict)
                        or not isinstance(ref.get("secret_ref"), str)
                        or not ref["secret_ref"].startswith("secret:")
                    ):
                        return
                    if field.get("required", True) and not ref:
                        return
                    continue
                if field_id in secret_refs:
                    return
                value = answers.get(field_id)
                if value is None or value == "" or value == []:
                    if field.get("required", True):
                        return
                    continue
                field_type = field.get("type", "text")
                if field_type == "boolean" and not isinstance(value, bool):
                    return
                if field_type == "number" and (
                    isinstance(value, bool) or not isinstance(value, (int, float))
                ):
                    return
                if field_type in {"text", "textarea", "select"} and not isinstance(value, str):
                    return
                if field_type == "multiselect" and (
                    not isinstance(value, list) or any(not isinstance(item, str) for item in value)
                ):
                    return
                if field.get("options") and not pending.get("allow_custom_response", True):
                    values = value if isinstance(value, list) else [value]
                    if any(item not in field["options"] for item in values):
                        return
        pending["resolved"] = True
        pending["submission"] = {"answers": answers, "secret_refs": secret_refs}
        if self.event_manager:
            self.event_manager.add_event(
                "UserInputSubmitted",
                {
                    "input_request_id": input_request_id,
                    "answer_keys": sorted(answers.keys()),
                    "secret_keys": sorted(secret_refs.keys()),
                },
            )
        workflow.logger.info(f"User input submitted: {input_request_id}")

    def _handle_remove_message(self, payload: dict[str, Any]) -> None:
        """Remove a queued message by ID before the agent sees it."""
        msg_id = payload["message_id"]
        self._message_queue = [m for m in self._message_queue if m["id"] != msg_id]
        if self.event_manager:
            self.event_manager.add_event(
                "MessageRemoved",
                {"message_id": msg_id},
            )
        workflow.logger.info(f"Message removed from queue: {msg_id}")
