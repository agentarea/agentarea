package workflows

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// Queue is the worker an activity runs on.
type Queue string

const (
	// QueueAgent is AGENTAREA_TEMPORAL_QUEUE, polled by `agentarea worker`.
	QueueAgent Queue = "agent"
	// QueueTrigger is AGENTAREA_TRIGGER_QUEUE.
	QueueTrigger Queue = "trigger"
	// QueueRunner is api.RunnerTaskQueue(client), polled by the serve process holding the client's runner.
	QueueRunner Queue = "runner"
)

// Retry is an activity's retry policy; MaxAttempts 0 retries until ScheduleToClose.
// Backoff coefficient is 2 everywhere.
type Retry struct {
	MaxAttempts int
	Initial     time.Duration
	Max         time.Duration
}

// ActivitySpec is one activity's contract: name, kind (decision 3d), payload
// types, the options its callers schedule it with, and its place in the
// implementation order of ACTIVITIES.md.
type ActivitySpec struct {
	Name  string
	Kind  durable.ActivityKind
	Queue Queue
	// In and Out are zero values of the payload types; Out nil means the activity returns only an error.
	In  any
	Out any

	StartToClose    time.Duration
	ScheduleToClose time.Duration
	ScheduleToStart time.Duration
	Heartbeat       time.Duration
	Retry           Retry
	// OutageWindow: ScheduleToClose is the run's OutageWait.RetryWindow and
	// StartToClose at most that; the workflow then waits out the outage.
	OutageWindow bool
	// WaitCancellation: a stopped run waits for the activity to settle (WAIT_CANCELLATION_COMPLETED).
	WaitCancellation bool
	// Unbounded: retries with no attempt or time limit, as the trigger batch's did.
	Unbounded bool
	Step      int
}

func retry(attempts int) Retry { return Retry{MaxAttempts: attempts, Initial: time.Second} }

func bookkeeping() Retry {
	return Retry{MaxAttempts: 10, Initial: time.Second, Max: 30 * time.Second}
}

func modelCall() Retry {
	return Retry{MaxAttempts: 8, Initial: 2 * time.Second, Max: time.Minute}
}

// ActivitySpecs is every activity the Go run registers.
func ActivitySpecs() []ActivitySpec {
	const activity = 5 * time.Minute
	const heartbeat = 30 * time.Second
	return []ActivitySpec{
		{Name: api.ActivityStoreContextOutput, Kind: durable.KindData, Queue: QueueAgent,
			In: StoreOutputRequest{}, Out: ContextResult{}, StartToClose: activity, Retry: retry(2), Step: 1},
		{Name: api.ActivitySearchHistory, Kind: durable.KindData, Queue: QueueAgent,
			In: SearchHistoryRequest{}, Out: ContextResult{}, StartToClose: activity, Retry: retry(2), Step: 1},
		{Name: api.ActivityRecallHistory, Kind: durable.KindData, Queue: QueueAgent,
			In: RecallHistoryRequest{}, Out: RecallHistoryResult{}, StartToClose: activity, Retry: retry(2), Step: 2},
		{Name: api.ActivityDelegatedTaskSpend, Kind: durable.KindControl, Queue: QueueAgent,
			In: DelegatedSpendRequest{}, Out: DelegatedSpendResult{}, StartToClose: activity, Retry: retry(3), Step: 3},
		{Name: api.ActivityCheckMonthlySpendCap, Kind: durable.KindControl, Queue: QueueAgent,
			In: MonthlySpendCapRequest{}, Out: MonthlySpendCapResult{}, StartToClose: activity, Retry: bookkeeping(), Step: 3},
		{Name: api.ActivityDeliverToRunner, Kind: durable.KindData, Queue: QueueAgent,
			In: DeliverToRunnerRequest{}, StartToClose: activity, Retry: bookkeeping(), Step: 4},
		{Name: api.ActivityValidateArtifacts, Kind: durable.KindData, Queue: QueueAgent,
			In: ArtifactValidationRequest{}, Out: ArtifactValidationResult{}, StartToClose: activity, Retry: retry(3), Step: 5},
		{Name: api.ActivityResolveRunConfig, Kind: durable.KindControl, Queue: QueueAgent,
			In: ResolveRunConfigRequest{}, Out: api.RunConfig{}, StartToClose: activity, Retry: retry(3), Step: 6},
		{Name: api.ActivityUpdateGovernanceSnapshot, Kind: durable.KindControl, Queue: QueueAgent,
			In: UpdateGovernanceSnapshotRequest{}, StartToClose: activity, Retry: bookkeeping(), Step: 7},
		{Name: api.ActivityRecord, Kind: durable.KindControl, Queue: QueueAgent,
			In: RecordRequest{}, Out: RecordResult{}, StartToClose: activity, ScheduleToClose: time.Hour,
			Retry: Retry{MaxAttempts: 0, Initial: time.Second, Max: 30 * time.Second}, Step: 7},
		{Name: api.ActivityActivateSkill, Kind: durable.KindData, Queue: QueueAgent,
			In: ActivateSkillRequest{}, Out: ActivateSkillResult{}, StartToClose: activity, Heartbeat: heartbeat,
			Retry: Retry{MaxAttempts: 0, Initial: 2 * time.Second, Max: time.Minute}, OutageWindow: true, Step: 8},
		{Name: api.ActivityCreateDelegationTask, Kind: durable.KindControl, Queue: QueueAgent,
			In: CreateDelegationTaskRequest{}, Out: CreateDelegationTaskResult{}, StartToClose: activity, Retry: retry(3), Step: 9},
		{Name: api.ActivityRunRunnerTurn, Kind: durable.KindData, Queue: QueueRunner,
			In: RunnerTurnRequest{}, Out: RunnerTurnResult{}, StartToClose: 12 * time.Hour, ScheduleToStart: 10 * time.Minute,
			Heartbeat: heartbeat, Retry: retry(1), WaitCancellation: true, Step: 10},
		{Name: api.ActivityCallLLM, Kind: durable.KindData, Queue: QueueAgent,
			In: LLMCallRequest{}, Out: LLMCallResult{}, StartToClose: 10 * time.Minute, Heartbeat: heartbeat,
			Retry: modelCall(), WaitCancellation: true, Step: 11},
		{Name: api.ActivityCompactMessages, Kind: durable.KindData, Queue: QueueAgent,
			In: CompactMessagesRequest{}, Out: CompactMessagesResult{}, StartToClose: 10 * time.Minute, Heartbeat: heartbeat,
			Retry: modelCall(), WaitCancellation: true, Step: 11},
		{Name: api.ActivityExecuteTool, Kind: durable.KindData, Queue: QueueAgent,
			In: ToolCallRequest{}, Out: ToolCallResult{}, StartToClose: 40 * time.Minute, Heartbeat: heartbeat,
			Retry: retry(3), WaitCancellation: true, Step: 12},
		{Name: api.ActivityGetRemoteTask, Kind: durable.KindData, Queue: QueueAgent,
			In: RemoteTaskRequest{}, Out: ToolCallResult{}, StartToClose: activity, Retry: retry(3), Step: 12},
		{Name: api.ActivityCancelRemoteTask, Kind: durable.KindData, Queue: QueueAgent,
			In: RemoteTaskRequest{}, StartToClose: activity, Retry: retry(3), Step: 12},
		{Name: api.ActivityStartUndispatchedTasks, Kind: durable.KindControl, Queue: QueueAgent,
			Out: StartUndispatchedResult{}, StartToClose: activity, Retry: retry(1), Step: 13},
		{Name: api.ActivitySyncCronSchedules, Kind: durable.KindControl, Queue: QueueTrigger,
			StartToClose: activity, Retry: retry(1), Step: 13},
		{Name: api.ActivityEvaluateTriggerConditions, Kind: durable.KindControl, Queue: QueueTrigger,
			In: EvaluateTriggerConditionsRequest{}, Out: EvaluateTriggerConditionsResult{}, StartToClose: 3 * time.Minute,
			Heartbeat: heartbeat, Retry: Retry{MaxAttempts: 5, Initial: time.Second, Max: 2 * time.Minute}, Step: 14},
		{Name: api.ActivityExecuteTrigger, Kind: durable.KindControl, Queue: QueueTrigger,
			In: ExecuteTriggerRequest{}, Out: ExecuteTriggerResult{}, StartToClose: 12 * time.Minute,
			Heartbeat: 2 * time.Minute, Retry: Retry{MaxAttempts: 3, Initial: 2 * time.Second, Max: 8 * time.Minute}, Step: 14},
		{Name: api.ActivityRecordTriggerExecution, Kind: durable.KindControl, Queue: QueueTrigger,
			In: RecordTriggerExecutionRequest{}, Out: RecordTriggerExecutionResult{}, StartToClose: 2 * time.Minute,
			Retry: Retry{MaxAttempts: 5, Initial: time.Second, Max: 30 * time.Second}, Step: 14},
		{Name: api.ActivityFireTriggerBatch, Kind: durable.KindControl, Queue: QueueTrigger,
			In: OpenBatch{}, Out: BatchResult{}, StartToClose: activity,
			Retry: Retry{MaxAttempts: 0, Initial: 2 * time.Second, Max: 5 * time.Minute}, Unbounded: true, Step: 14},
		{Name: api.ActivityCloseTriggerBatch, Kind: durable.KindControl, Queue: QueueTrigger,
			In: OpenBatch{}, Out: BatchResult{}, StartToClose: activity,
			Retry: Retry{MaxAttempts: 0, Initial: 2 * time.Second, Max: 5 * time.Minute}, Unbounded: true, Step: 14},
	}
}

// Kinds is each activity's kind by name, for the worker's registration check.
func Kinds() map[string]durable.ActivityKind {
	kinds := map[string]durable.ActivityKind{}
	for _, s := range ActivitySpecs() {
		kinds[s.Name] = s.Kind
	}
	return kinds
}
