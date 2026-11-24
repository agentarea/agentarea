package service_test

import (
	"encoding/json"
	"errors"
	"testing"

	"github.com/google/uuid"

	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

const processCode = "def process(event):\n    return [event]\n"

func enderSource(values, secrets map[string]string) catalogapi.BundleStreamSource {
	return catalogapi.BundleStreamSource{Type: "ender", Kind: "webhook", Config: map[string]string{}, Values: values, Secrets: secrets}
}

func TestBundleStreamCreateAndUpdateKeepWhatMatches(t *testing.T) {
	f := newSources(t, 100)
	b := service.BundleStreams{S: f.svc}
	secretID := uuid.NewString()
	f.secrets.Named[secretID] = ksecrets.Secret{ID: secretID, Name: "ender_token"} // pragma: allowlist secret
	f.secrets.Values["ender_token"] = "tok"
	archive, err := b.CreateStream(f.ctx, catalogapi.BundleStreamSpec{Name: "archive-" + uuid.NewString()[:6]})
	if err != nil {
		t.Fatal(err)
	}
	code := processCode
	spec := catalogapi.BundleStreamSpec{Name: "leads-" + uuid.NewString()[:6], Description: "Inbound",
		Sources: []catalogapi.BundleStreamSource{enderSource(nil, map[string]string{"token": "ender_token"})},
		Writers: []catalogapi.BundleStreamWriter{{Code: &code, Outputs: []string{archive}}, {Outputs: []string{archive}, Filter: map[string]any{"kinds": []any{"lead"}}}}}
	if problem, err := b.StreamProblem(f.ctx, spec); problem != "" || err != nil {
		t.Fatalf("problem = %q, %v", problem, err)
	}
	id, err := b.CreateStream(f.ctx, spec)
	if err != nil {
		t.Fatal(err)
	}
	if name, ok, err := b.StreamName(f.ctx, id); !ok || err != nil || name != spec.Name {
		t.Fatalf("name = %q %v %v", name, ok, err)
	}
	if got, ok, err := b.StreamNamed(f.ctx, spec.Name); !ok || err != nil || got != id {
		t.Fatalf("named = %q %v %v", got, ok, err)
	}
	sources, err := f.svc.ListSources(f.ctx, id)
	if err != nil || len(sources) != 1 {
		t.Fatalf("sources = %+v, %v", sources, err)
	}
	if refs := f.secrets.Refs[service.SecretConsumer+":"+sources[0].ID]; len(refs) != 1 || refs[0].SecretID != secretID {
		t.Fatalf("refs = %+v", refs)
	}
	subs, err := f.svc.ListSubscriptions(f.ctx, id)
	if err != nil || len(subs) != 2 {
		t.Fatalf("subscriptions = %+v, %v", subs, err)
	}
	processor := subs[0].ID
	if subs[0].Kind != domain.SubProcessor {
		processor = subs[1].ID
	}

	spec.Description = "Inbound, qualified"
	spec.Sources[0] = enderSource(map[string]string{"token": "plain"}, nil)
	spec.Writers = spec.Writers[:1]
	if err := b.UpdateStream(f.ctx, id, spec); err != nil {
		t.Fatal(err)
	}
	st, err := f.svc.GetStream(f.ctx, id)
	if err != nil || st.Description != "Inbound, qualified" {
		t.Fatalf("stream = %+v, %v", st, err)
	}
	after, err := f.svc.ListSources(f.ctx, id)
	if err != nil || len(after) != 1 || after[0].ID != sources[0].ID {
		t.Fatalf("sources after = %+v, %v (the matching source stays)", after, err)
	}
	var stored map[string]any
	if err := json.Unmarshal([]byte(f.secrets.Values[service.CredentialSecretName("ender", *after[0].CredentialKey)]), &stored); err != nil || stored["token"] != "plain" {
		t.Fatalf("credentials = %v, %v", stored, err)
	}
	if refs := f.secrets.Refs[service.SecretConsumer+":"+after[0].ID]; len(refs) != 0 {
		t.Fatalf("refs after = %+v", refs)
	}
	subs, err = f.svc.ListSubscriptions(f.ctx, id)
	if err != nil || len(subs) != 1 || subs[0].ID != processor {
		t.Fatalf("subscriptions after = %+v, %v (the processor stays, the forward goes)", subs, err)
	}

	changed := processCode + "# v2\n"
	spec.Writers[0].Code = &changed
	if err := b.UpdateStream(f.ctx, id, spec); err != nil {
		t.Fatal(err)
	}
	subs, err = f.svc.ListSubscriptions(f.ctx, id)
	if err != nil || len(subs) != 1 || subs[0].ID == processor || *subs[0].Code != changed {
		t.Fatalf("subscriptions after a code change = %+v, %v", subs, err)
	}
}

func TestBundleStreamRefusesWhatTheRoutesRefuse(t *testing.T) {
	f := newSources(t, 100)
	b := service.BundleStreams{S: f.svc}
	empty := "  "
	for _, c := range []struct {
		name string
		spec catalogapi.BundleStreamSpec
		want string
	}{
		{"unknown type", catalogapi.BundleStreamSpec{Name: "x", Sources: []catalogapi.BundleStreamSource{{Type: "nope", Kind: "webhook"}}},
			"source type 'nope' is not in the catalog"},
		{"missing credential", catalogapi.BundleStreamSpec{Name: "x", Sources: []catalogapi.BundleStreamSource{enderSource(nil, nil)}}, "Ender needs token"},
		{"empty code", catalogapi.BundleStreamSpec{Name: "x", Writers: []catalogapi.BundleStreamWriter{{Code: &empty, Outputs: []string{f.stream}}}},
			"The processor's code is empty"},
		{"bad filter", catalogapi.BundleStreamSpec{Name: "x", Writers: []catalogapi.BundleStreamWriter{{Outputs: []string{f.stream}, Filter: map[string]any{"kind": "x"}}}},
			"event_filter.kind: Extra inputs are not permitted"},
	} {
		t.Run(c.name, func(t *testing.T) {
			problem, err := b.StreamProblem(f.ctx, c.spec)
			if err != nil || problem != c.want {
				t.Fatalf("problem = %q, %v", problem, err)
			}
		})
	}
	before, err := f.svc.ListStreams(f.ctx, 100, 0)
	if err != nil {
		t.Fatal(err)
	}
	_, err = b.CreateStream(f.ctx, catalogapi.BundleStreamSpec{Name: "half-" + uuid.NewString()[:6],
		Sources: []catalogapi.BundleStreamSource{enderSource(nil, map[string]string{"token": "no_such_secret"})}})
	var refusal *catalogapi.BundleRefusal
	if !errors.As(err, &refusal) || refusal.Msg != "workspace secret 'no_such_secret' does not exist" {
		t.Fatalf("err = %v", err)
	}
	all, err := f.svc.ListStreams(f.ctx, 100, 0)
	if err != nil || len(all) != len(before) {
		t.Fatalf("streams left = %+v, %v (a refused create leaves nothing)", all, err)
	}
}

func TestBundleScheduleOnAStreamBindsTheTrigger(t *testing.T) {
	ctx, svc, _, agent, _ := newFixture(t, nil)
	st, err := svc.CreateStream(ctx, "leads", "")
	if err != nil {
		t.Fatal(err)
	}
	b := service.BundleTriggers{S: svc}
	n := catalogapi.BundleSchedule{Name: "ops:on-lead", Description: "Runs on stream leads", AgentID: agent, Text: "Qualify",
		StreamID: &st.ID, Filter: map[string]any{"kinds": []any{"lead.created"}}, Enabled: true}
	if problem, err := b.ScheduleProblem(ctx, n); problem != "" || err != nil {
		t.Fatalf("problem = %q, %v", problem, err)
	}
	id, err := b.CreateSchedule(ctx, n)
	if err != nil {
		t.Fatal(err)
	}
	got, ok, err := b.Trigger(ctx, id)
	if err != nil || !ok || got.StreamID == nil || *got.StreamID != st.ID {
		t.Fatalf("trigger = %+v %v %v", got, ok, err)
	}
	if err := b.UpdateTrigger(ctx, id, catalogapi.BundleTriggerUpdate{Description: "d", AgentID: agent, Text: "Qualify",
		Filter: map[string]any{"kinds": []any{"lead.updated"}}}); err != nil {
		t.Fatal(err)
	}
	tr, err := svc.Get(ctx, id)
	if err != nil || tr.Binding == nil || !sameKinds(tr.Binding.Filter, "lead.updated") {
		t.Fatalf("trigger after = %+v, %v", tr.Binding, err)
	}
}

func sameKinds(filter map[string]any, kind string) bool {
	kinds, _ := filter["kinds"].([]any)
	return len(kinds) == 1 && kinds[0] == kind
}

func TestBundleScheduleRunsASavedTaskAndSwitchesToAPrompt(t *testing.T) {
	ctx, svc, _, agent, _ := newFixture(t, nil)
	b := service.BundleTriggers{S: svc}
	task := uuid.NewString()
	id, err := b.CreateSchedule(ctx, catalogapi.BundleSchedule{Name: "ops:monday", Description: "Runs 0 9 * * 1 (UTC)", AgentID: agent,
		Cron: "0 9 * * 1", Timezone: "UTC", TaskDefinitionID: &task, Parameters: map[string]any{"week": "last"}, Enabled: true})
	if err != nil {
		t.Fatal(err)
	}
	tr, err := svc.Get(ctx, id)
	if err != nil || tr.TaskDefinitionID == nil || *tr.TaskDefinitionID != task || tr.TaskParameters["week"] != "last" {
		t.Fatalf("trigger = %+v, %v", tr, err)
	}
	cron, tz := "0 9 * * 1", "UTC"
	if err := b.UpdateTrigger(ctx, id, catalogapi.BundleTriggerUpdate{Description: "d", AgentID: agent, Text: "Write it yourself",
		Cron: &cron, Timezone: &tz, TaskDefinitionSet: true}); err != nil {
		t.Fatal(err)
	}
	if tr, err = svc.Get(ctx, id); err != nil || tr.TaskDefinitionID != nil || tr.TaskParameters["text"] != "Write it yourself" {
		t.Fatalf("trigger after = %+v, %v", tr, err)
	}
}
