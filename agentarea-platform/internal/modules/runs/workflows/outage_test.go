package workflows

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// skillOutage answers activate_skill_activity with ServiceUnreachable until up() is true.
type skillOutage struct {
	mu    sync.Mutex
	calls int
	up    func(calls int) bool
}

func (s *skillOutage) activate(_ context.Context, _ ActivateSkillRequest) (ActivateSkillResult, error) {
	s.mu.Lock()
	s.calls++
	n := s.calls
	s.mu.Unlock()
	if !s.up(n) {
		return ActivateSkillResult{}, temporal.NewApplicationError("blob store is unreachable", "ServiceUnreachable", map[string]any{"service": "Blob store"})
	}
	return ActivateSkillResult{Chars: 120, EstTokens: 30}, nil
}

func skillRun(t *testing.T, wait api.OutageWait, up func(int) bool) (*fakeRun, *skillOutage, func() error) {
	t.Helper()
	f := newFakeRun()
	f.cfg.Skills = []api.Skill{{ID: "skill-1", Name: "pdf", Description: "PDF work"}}
	f.cfg.OutageWait = wait
	f.llm[parentTask] = turns(
		calls(ToolCall{ID: "c1", Name: domain.ToolActivateSkill, Arguments: `{"skill_name": "pdf"}`}),
		text("Done with the skill."),
	)
	s := &skillOutage{up: up}
	env := newEnv(t, f)
	env.RegisterActivityWithOptions(s.activate, activity.RegisterOptions{Name: api.ActivityActivateSkill})
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))
	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	return f, s, env.GetWorkflowError
}

func statusesOf(f *fakeRun, task string) []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []string
	for _, s := range f.statuses[task] {
		out = append(out, s.Status)
	}
	return out
}

func TestSkillActivationWaitsOutAnOutageAndGoesOn(t *testing.T) {
	wait := api.OutageWait{RetryWindow: time.Minute, Backoff: []time.Duration{time.Minute, 5 * time.Minute}, Deadline: time.Hour}
	var recoveredAt int
	f, s, werr := skillRun(t, wait, func(n int) bool {
		if recoveredAt == 0 && n >= 9 {
			recoveredAt = n
		}
		return recoveredAt != 0
	})
	if err := werr(); err != nil {
		t.Fatalf("workflow failed: %v", err)
	}
	contains(t, f.events(parentTask), domain.EventTaskAwaitingInfra, domain.EventTaskInfraRecovered, domain.EventToolResult)
	awaiting := f.eventData(parentTask, domain.EventTaskAwaitingInfra)
	if awaiting[0]["service"] != "Blob store" || awaiting[0]["retry_in_seconds"] != float64(60) && awaiting[0]["retry_in_seconds"] != int64(60) {
		t.Fatalf("awaiting = %+v", awaiting[0])
	}
	contains(t, statusesOf(f, parentTask), StatusWaitingForInfra, "running", StatusCompleted)
	results := f.eventData(parentTask, domain.EventToolResult)
	if len(results) == 0 || results[0]["success"] != true {
		t.Fatalf("skill result = %+v (calls %d)", results, s.calls)
	}
}

func TestSkillActivationGivesUpAtTheDeadline(t *testing.T) {
	wait := api.OutageWait{RetryWindow: time.Minute, Backoff: []time.Duration{2 * time.Minute}, Deadline: 10 * time.Minute}
	f, _, werr := skillRun(t, wait, func(int) bool { return false })
	err := werr()
	if appErrorType(err) != ErrDependencyUnavailable {
		t.Fatalf("workflow error = %v, want DependencyUnavailable", err)
	}
	if msg := causeText(err); msg == "" || !strings.Contains(msg, "Blob store stayed unreachable for ") || !strings.Contains(msg, "while activating skill 'pdf'") {
		t.Fatalf("message = %q", msg)
	}
	if st := f.lastStatus(parentTask); st.Status != StatusFailed {
		t.Fatalf("final status = %+v", st)
	}
	for _, e := range f.events(parentTask) {
		if e == domain.EventTaskInfraRecovered {
			t.Fatal("a run that gave up must not report the service recovered")
		}
	}
}

func TestSpanFormatsWholeUnits(t *testing.T) {
	for d, want := range map[time.Duration]string{2 * time.Hour: "2 h", 10 * time.Minute: "10 min", 75 * time.Second: "75 s"} {
		if got := span(d); got != want {
			t.Errorf("span(%v) = %q, want %q", d, got, want)
		}
	}
}
