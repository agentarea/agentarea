package workflows

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// Launcher starts a stored task's AgentExecutionWorkflow on the agent queue
// (TemporalTaskManager.submit_task): workflow id task-{id}, one attempt, a
// start delay until scheduled_at, never a second run of the same id.
type Launcher struct {
	Exec  durable.Executor
	Queue string
	Now   func() time.Time
}

var _ service.RunLauncher = Launcher{}

// TaskWorkflowID is the workflow of a task's run.
func TaskWorkflowID(taskID string) string { return "task-" + taskID }

func (l Launcher) Launch(ctx context.Context, workspaceID string, t store.StoredTask) (service.Launched, error) {
	if l.Exec == nil || l.Queue == "" {
		return service.Launched{}, errors.New("launching a run needs the executor and the agent queue")
	}
	if workspaceID == "" {
		return service.Launched{}, fmt.Errorf("task %s missing required workspace_id", t.ID)
	}
	now := time.Now
	if l.Now != nil {
		now = l.Now
	}
	req, err := RunRequestFromTask(workspaceID, t)
	if err != nil {
		return service.Launched{}, err
	}
	var delay time.Duration
	if t.ScheduledAt != nil {
		delay = t.ScheduledAt.Sub(now())
		if delay < 0 {
			delay = 0
		}
	}
	id := TaskWorkflowID(t.ID)
	_, err = l.Exec.Start(ctx, api.WorkflowAgentExecution, id, []any{req}, durable.StartOptions{
		TaskQueue: l.Queue, RetryAttempts: 1, StartDelay: delay, StartOnce: true,
	})
	if err != nil && !errors.Is(err, durable.ErrAlreadyStarted) {
		return service.Launched{}, err
	}
	return service.Launched{ExecutionID: id, Scheduled: delay > 0}, nil
}

// RunRequestFromTask is the run of a stored task under the policy stored with
// it (TemporalTaskManager._workflow_args): the description is the query, the
// metadata the workflow metadata (with scheduled_at), the per-run selections
// read from the parameters as build_agent_config_activity reads them.
func RunRequestFromTask(workspaceID string, t store.StoredTask) (AgentRunRequest, error) {
	metadata := map[string]any{}
	for k, v := range t.Metadata {
		metadata[k] = v
	}
	if t.ScheduledAt != nil {
		metadata["scheduled_at"] = t.ScheduledAt.Format("2006-01-02T15:04:05.999999-07:00")
	}
	req := AgentRunRequest{
		TaskID: t.ID, AgentID: t.AgentID, UserID: t.CreatedBy, WorkspaceID: workspaceID,
		TaskQuery: t.Description, TaskParameters: t.Parameters, WorkflowMetadata: metadata,
		RequiresHumanApproval: metadata["requires_human_approval"] == true,
		Selections:            selectionsOf(t.Parameters, metadata),
	}
	if raw, ok := metadata["governance_snapshot"]; ok && raw != nil {
		b, err := json.Marshal(raw)
		if err != nil {
			return AgentRunRequest{}, err
		}
		if err := json.Unmarshal(b, &req.Governance); err != nil {
			return AgentRunRequest{}, fmt.Errorf("task %s governance snapshot: %w", t.ID, err)
		}
		req.Policy = req.Governance.EffectivePolicy
	}
	return req, nil
}

func selectionsOf(params, metadata map[string]any) RunSelections {
	s := RunSelections{
		MCPInstanceIDs: resourceIDs(params, "mcps", "mcp", "mcp_servers"),
		SkillIDs:       resourceIDs(params, "skills"),
		FileIDs:        stringsOf(params["files"]),
	}
	s.ModelOverride, _ = params["model_override"].(string)
	s.ProjectID, _ = metadata["project_id"].(string)
	s.TriggerEventFileName, _ = params["trigger_event_file"].(string)
	s.TriggerEvent, _ = params["trigger_event"].(map[string]any)
	return s
}

// resourceIDs is _task_resource_ids: the first key present, each item an id
// or an object naming one. A malformed reference is kept as written, so the
// run's first activity refuses it.
func resourceIDs(params map[string]any, keys ...string) []string {
	var value any
	for _, k := range keys {
		if v, ok := params[k]; ok && v != nil {
			value = v
			break
		}
	}
	list, ok := value.([]any)
	if !ok {
		return nil
	}
	var out []string
	seen := map[string]bool{}
	for _, item := range list {
		ref := item
		if m, isMap := item.(map[string]any); isMap {
			for _, k := range []string{"id", "instance_id", "skill_id"} {
				if v, ok := m[k]; ok && v != nil && v != "" {
					ref = v
					break
				}
			}
		}
		s := fmt.Sprint(ref)
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	return out
}

func stringsOf(v any) []string {
	list, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(list))
	for _, item := range list {
		out = append(out, fmt.Sprint(item))
	}
	return out
}
