package workflows

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

func TestARunAnswersItsStateNotAnEmptyEventList(t *testing.T) {
	f := newFakeRun()
	f.llm[parentTask] = turns(text("The answer is 42."))
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))
	result(t, env)
	for _, q := range []string{"get_workflow_events", "get_latest_events"} {
		if _, err := env.QueryWorkflow(q); err == nil {
			t.Fatalf("%s is still answered", q)
		}
	}
	if _, err := env.QueryWorkflow(api.QueryCurrentState); err != nil {
		t.Fatal(err)
	}
}
