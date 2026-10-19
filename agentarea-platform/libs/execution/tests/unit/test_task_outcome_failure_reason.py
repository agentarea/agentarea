"""A status update stores why the run stopped, and clears it once the task runs again."""

from agentarea_execution.activities.agent.task_state import task_outcome
from agentarea_execution.models import UpdateTaskStatusRequest


def _request(status: str, **fields) -> UpdateTaskStatusRequest:
    return UpdateTaskStatusRequest(task_id="t", status=status, workspace_id="w", **fields)


def test_a_blocked_run_stores_its_failure_reason_with_its_message():
    outcome = task_outcome(
        _request(
            "blocked",
            error_message="The model provider's account is out of credits",
            failure_reason="provider_out_of_credits",
        )
    )

    assert outcome.error == "The model provider's account is out of credits"
    assert outcome.metadata_patch == {"failure_reason": "provider_out_of_credits"}


def test_waiting_for_continuation_stores_the_limit_it_hit():
    outcome = task_outcome(
        _request(
            "waiting_for_continuation",
            error_message="Maximum iterations reached (2)",
            failure_reason="iteration_limit",
        )
    )

    assert outcome.error == "Maximum iterations reached (2)"
    assert outcome.metadata_patch == {"failure_reason": "iteration_limit"}


def test_running_again_clears_the_earlier_reason():
    assert task_outcome(_request("running")).metadata_patch == {"failure_reason": None}
    assert task_outcome(_request("completed")).metadata_patch == {"failure_reason": None}


def test_a_later_update_without_a_reason_keeps_the_stored_one():
    assert task_outcome(_request("failed")).metadata_patch is None
