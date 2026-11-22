package service

import (
	"context"
	"errors"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

type fakeBundleStreams struct {
	log      *deployLog
	names    map[string]string
	n        int
	problem  string
	created  []catalogapi.BundleStreamSpec
	updated  map[string]catalogapi.BundleStreamSpec
	failName string
}

func (f *fakeBundleStreams) StreamName(_ context.Context, id string) (string, bool, error) {
	n, ok := f.names[id]
	return n, ok, nil
}
func (f *fakeBundleStreams) StreamNamed(_ context.Context, name string) (string, bool, error) {
	for id, n := range f.names {
		if n == name {
			return id, true, nil
		}
	}
	return "", false, nil
}
func (f *fakeBundleStreams) StreamProblem(context.Context, catalogapi.BundleStreamSpec) (string, error) {
	return f.problem, nil
}
func (f *fakeBundleStreams) CreateStream(_ context.Context, spec catalogapi.BundleStreamSpec) (string, error) {
	if spec.Name == f.failName {
		return "", errors.New("streams down")
	}
	f.n++
	id := fmt.Sprintf("stream-%d", f.n)
	f.names[id] = spec.Name
	f.created = append(f.created, spec)
	f.log.add("create stream %s %s", id, streamText(spec))
	return id, nil
}
func (f *fakeBundleStreams) UpdateStream(_ context.Context, id string, spec catalogapi.BundleStreamSpec) error {
	f.updated[id] = spec
	f.log.add("update stream %s %s", id, streamText(spec))
	return nil
}
func (f *fakeBundleStreams) DeleteStream(_ context.Context, id string) error {
	delete(f.names, id)
	f.log.add("delete stream %s", id)
	return nil
}

func sortedText(m map[string]string) string {
	var out []string
	for k, v := range m {
		out = append(out, k+"="+v)
	}
	sort.Strings(out)
	return strings.Join(out, ",")
}

func streamText(s catalogapi.BundleStreamSpec) string {
	var parts []string
	for _, src := range s.Sources {
		parts = append(parts, fmt.Sprintf("source %s/%s config{%s} values{%s} secrets{%s}", src.Type, src.Kind, sortedText(src.Config),
			sortedText(src.Values), sortedText(src.Secrets)))
	}
	for _, w := range s.Writers {
		kind := "forward"
		if w.Code != nil {
			kind = "processor " + *w.Code
		}
		parts = append(parts, fmt.Sprintf("%s -> %s", kind, strings.Join(w.Outputs, ",")))
	}
	return s.Name + " [" + strings.Join(parts, "; ") + "]"
}

const streamsBundle = `
name: ops
setup:
  - {key: region, label: Region, default: eu}
  - {key: token, label: Token, type: secret}
agents:
  - {key: triage, name: Triage, model: us-model}
streams:
  - key: archive
    name: archive
    description: Everything, kept
  - key: leads
    name: Leads
    description: Inbound leads
    sources:
      - type: generic_webhook
        config: {region: "${setup.region}"}
        credentials: {signing_secret: "${secret.leads_hook}", token: "${setup.token}"}
    processors:
      - {code: "return event", outputs: [archive]}
    forwards:
      - {outputs: [audit-log], filter: {kinds: [lead.created]}}
automations:
  - key: on-lead
    agent: triage
    on: {stream: leads, filter: {kinds: [lead.created]}}
    prompt: Qualify the lead
  - {key: nightly, agent: triage, cron: "0 2 * * *", prompt: Sweep}
`

func TestLoadStreamsAndStreamSchedulesFromAFolder(t *testing.T) {
	files := StrPairs{
		{EntryFile, `schema_version: 1
name: ops
agents:
  include: agents/*.md
streams:
  include: streams/*.yaml
  archive:
    description: Everything, kept
schedules:
  on-lead:
    agent: triage
    on: {stream: leads, filter: {kinds: [lead.created]}}
    prompt: Qualify the lead
`},
		{"agents/triage.md", "---\nname: triage\nmodel: us-model\n---\nTriage leads."},
		{"streams/leads.yaml", `name: leads
display_name: Leads
description: Inbound leads
sources:
  - type: generic_webhook
    credentials: {signing_secret: "${secret.leads_hook}"}
processors:
  - code: return event
    outputs: [archive]
forwards:
  - outputs: [audit-log]
    filter: {kinds: [lead.created]}
`},
	}
	b, issues, err := LoadBundleFolder(files)
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 0 {
		t.Fatalf("issues = %+v", issues)
	}
	if len(b.Streams) != 2 {
		t.Fatalf("streams = %+v", b.Streams)
	}
	archive, leads := b.Streams[0], b.Streams[1]
	if archive.Key != "archive" || archive.Name != "archive" || archive.Description != "Everything, kept" || len(archive.Sources) != 0 {
		t.Errorf("archive = %+v", archive)
	}
	if leads.Key != "leads" || leads.Name != "Leads" || len(leads.Sources) != 1 || leads.Sources[0].Type != "generic_webhook" ||
		leads.Sources[0].Kind != "webhook" || len(leads.Processors) != 1 || *leads.Processors[0].Code != "return event" ||
		!reflect.DeepEqual(leads.Processors[0].Outputs, []string{"archive"}) || len(leads.Forwards) != 1 ||
		!reflect.DeepEqual(leads.Forwards[0].Outputs, []string{"audit-log"}) {
		t.Errorf("leads = %+v", leads)
	}
	if v, _ := leads.Sources[0].Credentials.Get("signing_secret"); v != "${secret.leads_hook}" {
		t.Errorf("credentials = %v", leads.Sources[0].Credentials)
	}
	a := b.Automations[0]
	if a.Key != "on-lead" || a.Cron != "" || a.On == nil || a.On.Stream != "leads" || a.Prompt != "Qualify the lead" {
		t.Errorf("automation = %+v", a)
	}
}

func TestAScheduleRunsOnCronOrOnAStreamNotBoth(t *testing.T) {
	for _, c := range []struct{ name, schedule string }{
		{"both", "cron: '0 2 * * *'\non: {stream: leads}"},
		{"neither", "timezone: UTC"},
	} {
		t.Run(c.name, func(t *testing.T) {
			files := StrPairs{{EntryFile, "schema_version: 1\nname: ops\nagents:\n  include: agents/*.md\nschedules:\n  include: schedules/*.md\n"},
				{"agents/triage.md", "---\nname: triage\nmodel: m\n---\n"},
				{"schedules/s.md", "---\nname: s\nagent: triage\n" + c.schedule + "\n---\nGo"}}
			_, _, err := LoadBundleFolder(files)
			if err == nil || !strings.Contains(err.Error(), "needs exactly one of 'cron' or 'on'") {
				t.Fatalf("err = %v", err)
			}
		})
	}
}

func TestStreamPlanResolvesOutputsAndSchedules(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, streamsBundle, nil)
	if len(p.Issues) != 0 {
		t.Fatalf("issues = %+v", p.Issues)
	}
	var got []string
	for _, e := range p.Entities {
		if e.Kind == KindStream || e.Kind == KindAutomation {
			got = append(got, fmt.Sprintf("%s:%s:%s:%s", e.Kind, e.Key, e.Status, *e.Detail))
		}
	}
	want := []string{
		"stream:archive:will_create:no sources, no writers",
		"stream:leads:will_create:1 source, 1 processor, 1 forward; signing_secret from secret 'leads_hook'",
		"automation:on-lead:will_create:on stream 'leads', enabled=False",
		"automation:nightly:will_create:cron '0 2 * * *' (UTC), enabled=False",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("entities = %q", got)
	}
}

func TestStreamPlanBlocksWhatCannotBeWired(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, `
name: ops
agents:
  - {key: triage, name: Triage, model: us-model}
streams:
  - key: a
    name: a
    sources: [{type: generic_webhook, credentials: {token: plain-text}}]
    forwards: [{outputs: [b, nowhere]}]
  - {key: b, name: b, forwards: [{outputs: [a]}]}
automations:
  - {key: s, agent: triage, on: {stream: missing}, prompt: go}
`, nil)
	want := []string{
		"streams write into each other in a cycle: a -> b -> a",
		"stream 'a' source generic_webhook credential 'token' must be ${secret.<name>} or reference ${setup.<key>}",
		"stream 'a' writes into 'nowhere', which is neither a stream of this bundle nor a stream of the workspace",
		"automation 's' runs on stream 'missing', which is neither a stream of this bundle nor a stream of the workspace",
	}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) {
		t.Fatalf("blocks = %q", got)
	}
}

func TestStreamInstallCreatesOutputsFirstAndBindsTheSchedule(t *testing.T) {
	f := newDeployFixture(t)
	streams := f.streams
	b := mustParse(t, streamsBundle)
	_, res, err := f.install(t, &b, nil)
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, c := range f.log.calls {
		if strings.Contains(c, "stream") || strings.Contains(c, "cron") {
			got = append(got, c)
		}
	}
	want := []string{
		"create stream stream-1 archive []",
		"create stream stream-2 Leads [source generic_webhook/webhook config{region=us} values{token=t0k} secrets{signing_secret=leads_hook}; " + // pragma: allowlist secret
			"processor return event -> stream-1; forward -> stream-audit]",
		`create schedule ops:on-lead on stream-2 filter map[kinds:[lead.created]] for agent-1 text=Qualify the lead`,
		`create cron ops:nightly "Runs 0 2 * * * (UTC)" for agent-1 text=Sweep`,
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("calls = %q", got)
	}
	if streams.created[1].Description != "Inbound leads" {
		t.Errorf("description = %q", streams.created[1].Description)
	}
	if got := actions(res); !reflect.DeepEqual(got[1:3], []string{"stream:archive:created:stream-1", "stream:leads:created:stream-2"}) {
		t.Errorf("entities = %v", got)
	}
}

func TestStreamInstallUndoesTheStreamsItMade(t *testing.T) {
	f := newDeployFixture(t)
	streams := f.streams
	f.triggers.cronErr = errors.New("scheduler down")
	b := mustParse(t, streamsBundle)
	if _, _, err := f.install(t, &b, nil); err == nil {
		t.Fatal("install succeeded")
	}
	if len(streams.names) != 1 {
		t.Fatalf("streams left = %v", streams.names)
	}
}

func TestStreamRedeployUpdatesOnlyTheChangedStream(t *testing.T) {
	f := newDeployFixture(t)
	first := mustParse(t, streamsBundle)
	_, res, err := f.install(t, &first, nil)
	if err != nil {
		t.Fatal(err)
	}
	prior := &priorInstall{bundle: first, result: res}
	changed := mustParse(t, strings.Replace(streamsBundle, `code: "return event"`, `code: "return None"`, 1))
	p, err := (&bundleAnalyzer{existence: f.w, checks: f.w, prior: prior, shapes: fakeShapes{}, supplied: wirejson.Object{}}).analyze(context.Background(), &changed)
	if err != nil {
		t.Fatal(err)
	}
	statuses := map[string]EntityStatus{}
	for _, e := range p.Entities {
		statuses[string(e.Kind)+":"+e.Key] = e.Status
	}
	if statuses["stream:leads"] != StatusWillUpdate || statuses["stream:archive"] != StatusUnchanged || statuses["automation:on-lead"] != StatusUnchanged {
		t.Fatalf("statuses = %v", statuses)
	}
	f.log.calls = nil
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{{KindStream, "leads"}: true}}
	res, err = in.install(context.Background(), &changed, wirejson.Object{}, prior, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(f.log.calls, []string{"update stream stream-2 Leads [source generic_webhook/webhook config{region=us} values{} " +
		"secrets{signing_secret=leads_hook}; processor return None -> stream-1; forward -> stream-audit]"}) { // pragma: allowlist secret
		t.Fatalf("calls = %q", f.log.calls)
	}
	if got := actions(res)[2]; got != "stream:leads:updated:stream-2" {
		t.Errorf("leads = %s", got)
	}
	if !reflect.DeepEqual(f.edits[len(f.edits)-1:], []string{"stream:stream-2"}) {
		t.Errorf("edit checks = %v", f.edits)
	}
}

func TestStreamRedeployBlocksWhatItCannotApply(t *testing.T) {
	f := newDeployFixture(t)
	first := mustParse(t, streamsBundle)
	_, res, err := f.install(t, &first, nil)
	if err != nil {
		t.Fatal(err)
	}
	prior := &priorInstall{bundle: first, result: res}
	changed := strings.NewReplacer("name: Leads", "name: Inbound", "on: {stream: leads, filter: {kinds: [lead.created]}}", "on: {stream: archive}",
		`cron: "0 2 * * *"`, "on: {stream: archive}").Replace(streamsBundle)
	b := mustParse(t, changed)
	p, err := (&bundleAnalyzer{existence: f.w, checks: f.w, prior: prior, shapes: fakeShapes{}, supplied: wirejson.Object{}}).analyze(context.Background(), &b)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{
		"stream 'leads' changes name from Leads to Inbound, which a redeploy cannot apply; give it a new key",
		"automation 'on-lead' changes its stream from leads to archive, which a redeploy cannot apply; give it a new key",
		"automation 'nightly' changes from a cron schedule to a stream trigger, which a redeploy cannot apply; give it a new key",
	}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) {
		t.Fatalf("blocks = %q", got)
	}
}

func TestAStreamAnotherBundleMadeIsNotTaken(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, "name: two\nstreams:\n  - {key: archive, name: archive}\n", func(a *bundleAnalyzer) {
		id := "stream-9"
		f.streams.names[id] = "elsewhere"
		a.others = []otherInstall{{id: "install-1", name: "one", result: InstallResult{Entities: []InstalledEntity{
			{Kind: KindStream, Key: "archive", Name: "archive", Action: ActionCreated, ID: &id}}}}}
	})
	want := []string{"stream 'archive' belongs to bundle 'one' (install install-1); a bundle owns what it creates, so give this one another name or deploy it from that bundle"}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) {
		t.Fatalf("blocks = %q", got)
	}
}
