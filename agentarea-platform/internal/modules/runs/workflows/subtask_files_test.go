package workflows

import (
	"strings"
	"testing"

	"go.temporal.io/sdk/activity"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// subtaskRun is a parent that delegates naming a file and completes declaring outputs/x.png,
// over a fake store where a save_file call writes into the task its run works on.
func subtaskRun(t *testing.T) *fakeRun {
	t.Helper()
	f := newFakeRun()
	f.files = map[string]map[string]bool{}
	f.cfg.Tools = append(f.cfg.Tools,
		api.ToolDefinition{Name: "delegate_to_helper", Parameters: map[string]any{"type": "object"}},
		api.ToolDefinition{Name: "save_file", Parameters: map[string]any{"type": "object"}})
	f.cfg.Bindings["save_file"] = api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: "agentarea/files", Method: "save_file"}}
	f.cfg.Delegates = map[string]api.Delegate{"delegate_to_helper": {AgentID: "agent-2", AgentName: "helper"}}
	f.tool = func(req ToolCallRequest) (ToolCallResult, error) {
		task := req.TaskID
		if shared, _ := req.RunMetadata[workspaceTaskKey].(string); shared != "" {
			task = shared
		}
		name, _ := req.Args["file_name"].(string)
		f.write(task, name)
		return ToolCallResult{Success: true, Result: "saved", Source: "builtin"}, nil
	}
	f.llm[parentTask] = turns(
		calls(ToolCall{ID: "call-1", Name: "delegate_to_helper", Arguments: `{"message": "draw a cat as inputs/brief.md says"}`}),
		calls(ToolCall{ID: "call-2", Name: domain.ToolCompletion, Arguments: `{"result": "Here it is.", "artifacts": ["outputs/x.png"]}`}),
	)
	return f
}

func parentCompletedWithTheChildsFile(t *testing.T, f *fakeRun, res AgentRunResult) {
	t.Helper()
	if !res.Success || res.ValidationState != "passed" {
		t.Fatalf("result = %+v", res)
	}
	if !f.files[parentTask]["outputs/x.png"] || len(f.files[childTask]) != 0 {
		t.Fatalf("stores = %v", f.files)
	}
	if len(f.created) != 1 || f.created[0].WorkspaceTaskID != parentTask {
		t.Fatalf("created = %+v", f.created)
	}
	for _, v := range f.validated {
		if v.TaskID != parentTask {
			t.Fatalf("a validation looked at task %s, not the shared one: %+v", v.TaskID, f.validated)
		}
	}
}

func TestAPlatformSubtaskWritesIntoItsParentsFiles(t *testing.T) {
	f := subtaskRun(t)
	f.llm[childTask] = turns(
		calls(ToolCall{ID: "c-1", Name: "save_file", Arguments: `{"file_name": "outputs/x.png", "contents": "png"}`}),
		text("Drew outputs/x.png."),
	)
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	parentCompletedWithTheChildsFile(t, f, result(t, env))
	var childCall *ToolCallRequest
	for i := range f.toolCalls {
		if f.toolCalls[i].TaskID == childTask {
			childCall = &f.toolCalls[i]
		}
	}
	if childCall == nil || childCall.RunMetadata[workspaceTaskKey] != parentTask {
		t.Fatalf("child tool calls = %+v", f.toolCalls)
	}
}

func TestARunnerSubtaskWritesIntoItsParentsFiles(t *testing.T) {
	f := subtaskRun(t)
	f.client = "client-1"
	runner := &fakeRunner{reply: func(int) (RunnerTurnResult, error) {
		f.mu.Lock()
		shared := f.created[0].WorkspaceTaskID
		f.mu.Unlock()
		f.write(shared, "outputs/x.png")
		return RunnerTurnResult{Status: "completed", Response: "Drew outputs/x.png."}, nil
	}}
	env := newEnv(t, f)
	env.RegisterActivityWithOptions(runner.run, activity.RegisterOptions{Name: api.ActivityRunRunnerTurn})
	env.RegisterActivityWithOptions(runner.deliver, activity.RegisterOptions{Name: api.ActivityDeliverToRunner})
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	parentCompletedWithTheChildsFile(t, f, result(t, env))
	if len(runner.turns) != 1 || runner.turns[0].TaskID != childTask || !strings.Contains(runner.turns[0].Message, "inputs/brief.md") {
		t.Fatalf("runner turns = %+v", runner.turns)
	}
}

func TestAParentDeclaringAFileNoSubtaskWroteRepairsIt(t *testing.T) {
	f := subtaskRun(t)
	f.llm[childTask] = turns(text("I could not draw it."))
	f.llm[parentTask] = turns(
		calls(ToolCall{ID: "call-1", Name: "delegate_to_helper", Arguments: `{"message": "draw a cat"}`}),
		calls(ToolCall{ID: "call-2", Name: domain.ToolCompletion, Arguments: `{"result": "Here it is.", "artifacts": ["outputs/x.png"]}`}),
		calls(complete("call-3", "The helper could not draw it.")),
	)
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	res := result(t, env)
	if !res.Success || res.FinalResponse != "The helper could not draw it." {
		t.Fatalf("result = %+v", res)
	}
}
