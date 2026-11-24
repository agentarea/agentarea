package api

// Workflow names. The run surface in serve starts and signals them.
const (
	WorkflowAgentExecution    = "AgentExecutionWorkflow"
	WorkflowRemoteDelegation  = "RemoteDelegationWorkflow"
	WorkflowUndispatchedTasks = "UndispatchedTaskReconcilerWorkflow"
	WorkflowCronScheduleSync  = "CronScheduleSyncWorkflow"
	WorkflowTriggerExecution  = "TriggerExecutionWorkflow"
	WorkflowTriggerBatch      = "TriggerBatchWorkflow"
)

// Activity names as registered. Names a Python activity kept keep its name, so
// the Python source stays greppable as the specification; ACTIVITIES.md maps
// every Python activity to one of these or says why it is not ported.
const (
	ActivityResolveRunConfig          = "resolve_run_config_activity"
	ActivityCheckMonthlySpendCap      = "check_monthly_spend_cap_activity"
	ActivityRecord                    = "record_activity"
	ActivityUpdateGovernanceSnapshot  = "update_task_governance_snapshot_activity"
	ActivityCreateDelegationTask      = "create_delegation_task_activity"
	ActivityDelegatedTaskSpend        = "delegated_task_spend_activity"
	ActivityCallLLM                   = "call_llm_activity"
	ActivityCompactMessages           = "compact_messages_activity"
	ActivityExecuteTool               = "execute_mcp_tool_activity"
	ActivityGetRemoteTask             = "get_remote_task_activity"
	ActivityCancelRemoteTask          = "cancel_remote_task_activity"
	ActivityValidateArtifacts         = "validate_artifacts_activity"
	ActivityActivateSkill             = "activate_skill_activity"
	ActivityRecallHistory             = "recall_history_activity"
	ActivityStoreContextOutput        = "store_context_output"
	ActivityReadContextOutput         = "read_context_output"
	ActivitySearchHistory             = "search_history"
	ActivityRunRunnerTurn             = "run_runner_turn_activity"
	ActivityDeliverToRunner           = "deliver_to_runner_activity"
	ActivityStartUndispatchedTasks    = "start_undispatched_tasks_activity"
	ActivitySyncCronSchedules         = "sync_cron_schedules_activity"
	ActivityEvaluateTriggerConditions = "evaluate_trigger_conditions_activity"
	ActivityExecuteTrigger            = "execute_trigger_activity"
	ActivityRecordTriggerExecution    = "record_trigger_execution_activity"
	ActivityFireTriggerBatch          = "fire_trigger_batch_activity"
	ActivityCloseTriggerBatch         = "close_trigger_batch_activity"
)

// RunnerTaskQueue is the queue a client's runner turns wait on; the serve
// process holding that client's runner socket polls it.
func RunnerTaskQueue(clientID string) string { return "runner-turns-" + clientID }
