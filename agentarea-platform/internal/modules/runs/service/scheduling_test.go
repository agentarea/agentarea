package service

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

type fakeSchedules struct {
	infos   map[string]durable.ScheduleInfo
	ensured []durable.Schedule
	refuse  string
}

func (f *fakeSchedules) Ensure(_ context.Context, s durable.Schedule) error {
	if s.ID == f.refuse {
		return errors.New("refused")
	}
	f.ensured = append(f.ensured, s)
	return nil
}

func (f *fakeSchedules) Describe(_ context.Context, id string) (durable.ScheduleInfo, error) {
	info, ok := f.infos[id]
	if !ok {
		return durable.ScheduleInfo{}, durable.ErrNotFound
	}
	return info, nil
}

func (f *fakeSchedules) Delete(context.Context, string) error { return nil }

// described is a schedule as the server describes it: cron normalised away,
// the action's arguments as JSON.
func described(s durable.Schedule) durable.ScheduleInfo {
	info := durable.ScheduleInfo{ID: s.ID, Workflow: s.Workflow, WorkflowID: s.WorkflowID, TaskQueue: s.TaskQueue,
		TimeZone: s.TimeZone, CatchupWindow: s.CatchupWindow, Paused: s.Paused, Note: s.Note}
	for _, a := range s.Args {
		b, _ := json.Marshal(a)
		info.Args = append(info.Args, b)
	}
	return info
}

type fakeTriggers struct {
	rows     map[string]CronTrigger
	order    []string
	state    map[string]TriggerState
	firing   TriggerFiring
	fired    []TriggerFire
	fireErr  error
	met      bool
	metErr   error
	recorded []TriggerExecutionRecord
}

func (f *fakeTriggers) CronTriggers(context.Context) ([]CronTrigger, error) {
	var out []CronTrigger
	for _, id := range f.order {
		out = append(out, CronTrigger{ID: id})
	}
	return out, nil
}

func (f *fakeTriggers) CronTrigger(_ context.Context, id string) (CronTrigger, bool, error) {
	r, ok := f.rows[id]
	return r, ok, nil
}

func (f *fakeTriggers) Trigger(_ context.Context, id string) (TriggerState, error) {
	s, ok := f.state[id]
	if !ok {
		return TriggerState{}, ErrNotFound
	}
	return s, nil
}

func (f *fakeTriggers) EvaluateConditions(context.Context, string, map[string]any) (bool, error) {
	return f.met, f.metErr
}

func (f *fakeTriggers) Fire(_ context.Context, fire TriggerFire) (TriggerFiring, error) {
	f.fired = append(f.fired, fire)
	return f.firing, f.fireErr
}

func (f *fakeTriggers) RecordExecution(_ context.Context, _ string, r TriggerExecutionRecord) (RecordedTriggerExecution, error) {
	f.recorded = append(f.recorded, r)
	return RecordedTriggerExecution{ID: "exec-1"}, nil
}

func TestSyncCronSchedulesBringsEachScheduleInLine(t *testing.T) {
	inLine := api.CronTriggerSchedule("t-ok", "0 9 * * *", "Europe/Moscow", "triggers", false)
	stale := api.CronTriggerSchedule("t-stale", "0 9 * * *", "UTC", "triggers", false)
	sch := &fakeSchedules{infos: map[string]durable.ScheduleInfo{
		inLine.ID: described(inLine),
		stale.ID:  described(stale),
	}, refuse: api.CronTriggerScheduleID("t-refused")}
	tr := &fakeTriggers{order: []string{"t-ok", "t-stale", "t-new", "t-gone", "t-blank", "t-refused"}, rows: map[string]CronTrigger{
		"t-ok":      {ID: "t-ok", CronExpression: "0 9 * * *", TimeZone: "Europe/Moscow", Active: true},
		"t-stale":   {ID: "t-stale", CronExpression: "0 9 * * *", Active: false},
		"t-new":     {ID: "t-new", CronExpression: "*/5 * * * *", Active: true},
		"t-blank":   {ID: "t-blank", Active: true},
		"t-refused": {ID: "t-refused", CronExpression: "0 0 * * *", Active: true},
	}}
	s := NewScheduling(SchedulingDeps{Triggers: tr, Schedules: sch, TriggerQueue: "triggers", Log: quiet()})
	r, err := s.SyncCronSchedules(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if r.Changed != 2 || r.Failed != 2 {
		t.Fatalf("%+v", r)
	}
	if len(sch.ensured) != 2 || sch.ensured[0].ID != stale.ID || !sch.ensured[0].Paused || sch.ensured[0].TimeZone != "UTC" {
		t.Fatalf("%+v", sch.ensured)
	}
	n := sch.ensured[1]
	if n.WorkflowID != "trigger-execution-t-new-{{.ScheduledTime}}" || n.CatchupWindow != time.Hour || n.TaskQueue != "triggers" ||
		n.Args[0] != "t-new" || n.Cron[0] != "*/5 * * * *" {
		t.Fatalf("%+v", n)
	}
}

func TestApplyCronScheduleSeesAMovedQueue(t *testing.T) {
	old := api.CronTriggerSchedule("t1", "0 9 * * *", "UTC", "old-queue", false)
	sch := &fakeSchedules{infos: map[string]durable.ScheduleInfo{old.ID: described(old)}}
	s := NewScheduling(SchedulingDeps{Schedules: sch, TriggerQueue: "triggers", Log: quiet()})
	changed, err := s.ApplyCronSchedule(context.Background(), "t1", "0 9 * * *", "UTC", false)
	if err != nil || !changed || sch.ensured[0].TaskQueue != "triggers" {
		t.Fatalf("%v %v %+v", changed, err, sch.ensured)
	}
}

func TestExecuteTriggerOutcomes(t *testing.T) {
	ctx := context.Background()
	tr := &fakeTriggers{state: map[string]TriggerState{"t1": {ID: "t1", Active: true}, "off": {ID: "off"}}}
	s := NewScheduling(SchedulingDeps{Triggers: tr, Log: quiet()})
	if _, err := s.ExecuteTrigger(ctx, "t1", nil, ""); err == nil {
		t.Fatal("ran outside a workflow")
	}
	_, err := s.ExecuteTrigger(ctx, "gone", nil, "wf")
	var appErr *durable.ApplicationError
	if !errors.As(err, &appErr) || appErr.Type != "TriggerNotFoundError" || !appErr.NonRetryable {
		t.Fatalf("%v", err)
	}
	if r, err := s.ExecuteTrigger(ctx, "off", nil, "wf"); err != nil || r.Status != TriggerSkipped || r.Reason != SkipTriggerInactive || len(tr.fired) != 0 {
		t.Fatalf("%+v %v", r, err)
	}
	for _, c := range []struct {
		firing         TriggerFiring
		status, reason string
	}{
		{TriggerFiring{Outcome: "reacted", TaskID: "task-1"}, TriggerSuccess, ""},
		{TriggerFiring{Outcome: "skipped", BlockedBy: "task-0", Verdict: true}, TriggerSkipped, SkipPreviousRunActive},
		{TriggerFiring{Outcome: "skipped", Verdict: true}, TriggerSkipped, SkipConditionsNotMet},
		{TriggerFiring{Outcome: "skipped"}, TriggerSkipped, SkipTriggerInactive},
		{TriggerFiring{Outcome: "error", Reason: "agent archived"}, TriggerFailed, ""},
	} {
		tr.firing = c.firing
		r, err := s.ExecuteTrigger(ctx, "t1", map[string]any{"source": "cron"}, "trigger-execution-t1-2026")
		if err != nil || r.Status != c.status || r.Reason != c.reason {
			t.Fatalf("%+v: %+v %v", c.firing, r, err)
		}
	}
	f := tr.fired[0]
	if f.TaskID != ScheduledTaskID("trigger-execution-t1-2026") || f.Provenance.CorrelationID != "trigger-execution-t1-2026" || f.Provenance.OriginType != "trigger" {
		t.Fatalf("%+v", f)
	}
}

func TestScheduledTaskIDIsAUUID5PerWorkflow(t *testing.T) {
	if got := ScheduledTaskID("trigger-execution-x-2026-01-01T00:00:00Z"); len(got) != 36 || got[14] != '5' {
		t.Fatal(got)
	}
	a, again := ScheduledTaskID("a"), ScheduledTaskID("a")
	if a == ScheduledTaskID("b") || a != again {
		t.Fatal("not deterministic per workflow")
	}
}

func TestEvaluateTriggerConditionsFailureIsUnmet(t *testing.T) {
	s := NewScheduling(SchedulingDeps{Triggers: &fakeTriggers{met: true, metErr: errors.New("llm down")}, Log: quiet()})
	if s.EvaluateTriggerConditions(context.Background(), "t1", nil) {
		t.Fatal("an error met the conditions")
	}
}
