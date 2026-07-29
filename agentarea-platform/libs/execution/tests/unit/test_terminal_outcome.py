from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow


def test_iteration_limit_records_machine_and_human_failure_reason():
    workflow = AgentExecutionWorkflow()

    workflow._record_unsuccessful_termination(
        "iteration_limit", "Maximum iterations reached (10)"
    )

    assert workflow.state.failure_reason == "iteration_limit"
    assert workflow.state.error_message == "Maximum iterations reached (10)"


def test_budget_limit_records_machine_and_human_failure_reason():
    workflow = AgentExecutionWorkflow()

    workflow._record_unsuccessful_termination(
        "budget_exceeded", "Budget exceeded ($1.00/$1.00)"
    )

    assert workflow.state.failure_reason == "budget_exceeded"
    assert workflow.state.error_message == "Budget exceeded ($1.00/$1.00)"


def test_successful_state_is_not_overwritten_by_stop_bookkeeping():
    workflow = AgentExecutionWorkflow()
    workflow.state.success = True

    workflow._record_unsuccessful_termination(
        "iteration_limit", "Maximum iterations reached (10)"
    )

    assert workflow.state.failure_reason is None
    assert workflow.state.error_message is None


def test_follow_up_resets_prior_turn_completion_before_exhaustion():
    workflow = AgentExecutionWorkflow()
    workflow._completion_event_published = True
    workflow.state.success = True
    workflow.state.final_response = "stale successful response"
    workflow.state.validation_state = "passed"

    workflow._reset_for_follow_up()
    workflow._record_unsuccessful_termination(
        "iteration_limit", "Maximum iterations reached (10)"
    )

    assert workflow._completion_event_published is False
    assert workflow.state.success is False
    assert workflow.state.final_response == ""
    assert workflow.state.validation_state == "pending"
    assert workflow.state.failure_reason == "iteration_limit"
    assert workflow.state.error_message == "Maximum iterations reached (10)"
