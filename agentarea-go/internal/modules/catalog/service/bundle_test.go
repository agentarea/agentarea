package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

const demoBundle = `
schema_version: "0.1.0"
name: demo
description: Demo bundle
setup:
  - key: token
    label: Token
    type: secret
    required: true
  - key: region
    label: Region
    type: string
    default: eu
skills:
  - key: s1
    name: Writer
    content: "---\nname: writer\ndescription: writes things\n---\nBody"
agents:
  - key: agent
    name: Demo
    description: d
    instruction: be helpful
    model: "${setup.region}-model"
    skills: [s1]
automations:
  - key: daily
    cron: "0 9 * * *"
    timezone: UTC
    agent: agent
    prompt: go
policies:
  - key: cap
    subject: agent
    target: "tool:web_search"
    effect: deny
`

func demoValues() wirejson.Object {
	return wirejson.Object{{Key: "token", Value: "t0k"}, {Key: "region", Value: "us"}}
}

func mustParse(t *testing.T, src string) Bundle {
	t.Helper()
	b, err := ParseBundle(src)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// fakeShapes accepts every skill, rule and context secret.
type fakeShapes struct{}

func (fakeShapes) SkillProblem(string) string { return "" }
func (fakeShapes) SkillMainFile(paths []string) (string, bool) {
	for _, p := range paths {
		if strings.EqualFold(p, "SKILL.md") {
			return p, true
		}
	}
	return "", false
}
func (fakeShapes) CarriesSecretRef(any) bool                   { return false }
func (fakeShapes) RuleProblem(catalogapi.BundleRule) string    { return "" }
func (fakeShapes) ContextSecretLength() (minimum, maximum int) { return 16, 512 }

// The values are Python's: analyzer.spec_fingerprint and BundleAnalyzer.analyze
// of the same bundle and setup values.
func TestBundleFingerprintAndDigestMatchPython(t *testing.T) {
	b := mustParse(t, demoBundle)
	values := effectiveSetup(&b, demoValues(), nil)
	for _, c := range []struct {
		spec bundleSpec
		want string
	}{
		{b.Agents[0], "3fcb6f00ca46ec9bcb24f4066d586b97b988288d9297be0bfd75ff7557cd720c"},
		{b.Automations[0], "8875b13caf4a17381f48c2c69858df9df93dee766f06df2ab931792e5f2772c4"},
	} {
		got, err := specFingerprint(&b, c.spec, values)
		if err != nil || got != c.want {
			t.Errorf("fingerprint of %s = %s, %v; want %s", c.spec.specKey(), got, err, c.want)
		}
	}
	p, err := (&bundleAnalyzer{shapes: fakeShapes{}, supplied: demoValues()}).analyze(context.Background(), &b)
	if err != nil {
		t.Fatal(err)
	}
	if p.PlanDigest == nil || *p.PlanDigest != "82e895ae36fa8aff8b6eb0e18c3805166fe649671e65b63ea976aefb96d5e759" {
		t.Errorf("digest = %v", p.PlanDigest)
	}
	if !p.Installable || len(p.Issues) != 0 {
		t.Errorf("installable = %v, issues %v", p.Installable, p.Issues)
	}
	var got []string
	for _, e := range p.Entities {
		got = append(got, fmt.Sprintf("%s:%s:%s", e.Kind, e.Key, e.Status))
	}
	want := []string{"skill:s1:will_create", "agent:agent:will_create", "automation:daily:will_create", "policy:cap:will_create"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("entities = %v, want %v", got, want)
	}
}

func TestValidateAnalyzeRequest(t *testing.T) {
	obj := func(members ...wirejson.Member) wirejson.Object { return wirejson.Object(members) }
	cases := []struct {
		name string
		body wirejson.Object
		msg  string
		typ  string
		loc  []any
	}{
		{"none", obj(), "Value error, provide exactly one of 'source', 'source_url', 'files' or 'bundle'", "value_error", []any{"body"}},
		{"blank source", obj(wirejson.Member{Key: "source", Value: "  "}), "Value error, provide exactly one of 'source', 'source_url', 'files' or 'bundle'", "value_error", []any{"body"}},
		{"two", obj(wirejson.Member{Key: "source", Value: "x"}, wirejson.Member{Key: "source_url", Value: "https://x"}),
			"Value error, provide exactly one of 'source', 'source_url', 'files' or 'bundle'", "value_error", []any{"body"}},
		{"bad path", obj(wirejson.Member{Key: "files", Value: obj(wirejson.Member{Key: "../agent.yaml", Value: "x"})}),
			"Value error, invalid path '../agent.yaml': empty, '.' or '..' segment", "value_error", []any{"body"}},
		{"absolute path", obj(wirejson.Member{Key: "files", Value: obj(wirejson.Member{Key: "/agent.yaml", Value: "x"})}),
			"Value error, invalid path '/agent.yaml': must be a relative POSIX path", "value_error", []any{"body"}},
		{"too large", obj(wirejson.Member{Key: "files", Value: obj(wirejson.Member{Key: "agent.yaml", Value: strings.Repeat("x", BundleMaxBytes)})}),
			"Value error, agent folder exceeds 5MB limit", "value_error", []any{"body"}},
		{"source type", obj(wirejson.Member{Key: "source", Value: true}), "Input should be a valid string", "string_type", []any{"body", "source"}},
		{"file text type", obj(wirejson.Member{Key: "files", Value: obj(wirejson.Member{Key: "agent.yaml", Value: wirejson.Object{}})}),
			"Input should be a valid string", "string_type", []any{"body", "files", "agent.yaml"}},
		{"setup null", obj(wirejson.Member{Key: "source", Value: "x"}, wirejson.Member{Key: "setup_values", Value: nil}),
			"Input should be a valid dictionary", "dict_type", []any{"body", "setup_values"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, errs := ValidateAnalyzeRequest(c.body)
			if len(errs) != 1 || errs[0].Msg != c.msg || errs[0].Type != c.typ || !reflect.DeepEqual(errs[0].Loc, c.loc) {
				t.Fatalf("errors = %+v", errs)
			}
		})
	}
	req, errs := ValidateAnalyzeRequest(obj(wirejson.Member{Key: "files", Value: obj(wirejson.Member{Key: "agent.yaml", Value: "name: a"})}))
	if errs != nil || len(req.Files) != 1 || req.SetupValues == nil {
		t.Fatalf("files request = %+v, %v", req, errs)
	}
}

func TestValidateInstallRequest(t *testing.T) {
	_, errs := ValidateInstallRequest(wirejson.Object{{Key: "plan_digest", Value: ""}})
	if len(errs) != 2 || errs[0].Type != "missing" || !reflect.DeepEqual(errs[0].Loc, []any{"body", "bundle"}) ||
		errs[1].Type != "string_too_short" || !reflect.DeepEqual(errs[1].Loc, []any{"body", "plan_digest"}) {
		t.Fatalf("errors = %+v", errs)
	}
	agents := []any{wirejson.Object{{Key: "key", Value: "a"}}}
	_, errs = ValidateInstallRequest(wirejson.Object{{Key: "bundle", Value: wirejson.Object{{Key: "name", Value: "x"}, {Key: "agents", Value: agents}}},
		{Key: "plan_digest", Value: "d"}})
	if len(errs) != 1 || errs[0].Type != "missing" || !reflect.DeepEqual(errs[0].Loc, []any{"body", "bundle", "agents", 0, "name"}) {
		t.Fatalf("errors = %+v", errs)
	}
	req, errs := ValidateInstallRequest(wirejson.Object{{Key: "bundle", Value: wirejson.Object{{Key: "name", Value: "x"}}}, {Key: "plan_digest", Value: "d"}})
	if errs != nil || req.Bundle.SchemaVersion != "0.1.0" || req.PlanDigest != "d" {
		t.Fatalf("request = %+v, %v", req, errs)
	}
}

// --- installer fakes --------------------------------------------------------

type deployLog struct{ calls []string }

func (l *deployLog) add(format string, a ...any) {
	l.calls = append(l.calls, fmt.Sprintf(format, a...))
}

type fakeBundleAgents struct {
	log     *deployLog
	live    map[string]bool
	n       int
	updates []catalogapi.BundleAgentUpdate
}

func (f *fakeBundleAgents) next(prefix string) string {
	f.n++
	id := fmt.Sprintf("%s-%d", prefix, f.n)
	f.live[id] = true
	return id
}
func (f *fakeBundleAgents) AgentLive(_ context.Context, _ authn.Caller, id string) (bool, error) {
	return f.live[id], nil
}
func (f *fakeBundleAgents) AgentProblem(context.Context, authn.Caller, catalogapi.BundleAgentConfig) (string, error) {
	return "", nil
}
func (f *fakeBundleAgents) CreateAgent(_ context.Context, _ authn.Caller, in catalogapi.BundleAgentNew) (string, error) {
	id := f.next("agent")
	f.log.add("create agent %s model=%s skills=%v", in.Name, in.ModelID, in.SkillIDs)
	return id, nil
}
func (f *fakeBundleAgents) UpdateAgent(_ context.Context, _ authn.Caller, id string, in catalogapi.BundleAgentUpdate) error {
	f.updates = append(f.updates, in)
	f.log.add("update agent %s", id)
	return nil
}
func (f *fakeBundleAgents) DeleteAgent(_ context.Context, _ authn.Caller, id string) error {
	delete(f.live, id)
	f.log.add("delete agent %s", id)
	return nil
}
func (f *fakeBundleAgents) SkillLive(_ context.Context, _ authn.Caller, id string) (bool, error) {
	return f.live[id], nil
}
func (fakeBundleAgents) SkillProblem(string) string { return "" }
func (fakeBundleAgents) SkillMainFile(paths []string) (string, bool) {
	return fakeShapes{}.SkillMainFile(paths)
}
func (f *fakeBundleAgents) CreateSkill(_ context.Context, _ authn.Caller, in catalogapi.BundleSkillNew) (string, error) {
	f.log.add("create skill %s", in.Name)
	return f.next("skill"), nil
}
func (f *fakeBundleAgents) ReplaceSkillFiles(_ context.Context, _ authn.Caller, id string, files []catalogapi.BundleFile) error {
	f.log.add("replace skill %s %d files", id, len(files))
	return nil
}
func (f *fakeBundleAgents) RenameSkill(_ context.Context, _ authn.Caller, id, name string) error {
	f.log.add("rename skill %s %s", id, name)
	return nil
}
func (f *fakeBundleAgents) DeleteSkill(_ context.Context, _ authn.Caller, id string) error {
	delete(f.live, id)
	f.log.add("delete skill %s", id)
	return nil
}

type fakeBundleTriggers struct {
	log      *deployLog
	triggers map[string]catalogapi.BundleTrigger
	n        int
	cronErr  error
}

func (f *fakeBundleTriggers) Trigger(_ context.Context, id string) (catalogapi.BundleTrigger, bool, error) {
	t, ok := f.triggers[id]
	return t, ok, nil
}
func (f *fakeBundleTriggers) Triggers(context.Context) ([]catalogapi.BundleTrigger, error) {
	var out []catalogapi.BundleTrigger
	for _, t := range f.triggers {
		out = append(out, t)
	}
	return out, nil
}
func (f *fakeBundleTriggers) CronProblem(context.Context, catalogapi.BundleCron) (string, error) {
	return "", nil
}
func (f *fakeBundleTriggers) CreateCron(_ context.Context, n catalogapi.BundleCron) (string, error) {
	if f.cronErr != nil {
		return "", f.cronErr
	}
	f.n++
	id := fmt.Sprintf("trigger-%d", f.n)
	f.triggers[id] = catalogapi.BundleTrigger{ID: id, Name: n.Name, AgentID: n.AgentID, Active: n.Enabled}
	f.log.add("create cron %s %q for %s text=%s", n.Name, n.Description, n.AgentID, n.Text)
	return id, nil
}
func (f *fakeBundleTriggers) CreateChannel(context.Context, catalogapi.BundleChannelNew) (catalogapi.BundleChannelCreated, error) {
	return catalogapi.BundleChannelCreated{}, errors.New("unused")
}
func (f *fakeBundleTriggers) DeleteChannel(context.Context, catalogapi.BundleChannelCreated) error {
	return nil
}
func (f *fakeBundleTriggers) DeleteTrigger(_ context.Context, id string) error {
	delete(f.triggers, id)
	f.log.add("delete trigger %s", id)
	return nil
}
func (f *fakeBundleTriggers) UpdateTrigger(_ context.Context, id string, u catalogapi.BundleTriggerUpdate) error {
	f.log.add("update trigger %s", id)
	return nil
}
func (f *fakeBundleTriggers) SetTriggerEnabled(_ context.Context, id string, enabled bool) error {
	f.log.add("enable trigger %s %v", id, enabled)
	return nil
}
func (f *fakeBundleTriggers) ChannelCredentials(context.Context, string) (catalogapi.BundleChannelCredentials, bool, error) {
	return catalogapi.BundleChannelCredentials{}, false, nil
}
func (f *fakeBundleTriggers) SetChannelCredentials(context.Context, catalogapi.BundleChannelCredentials) error {
	return nil
}

type fakeBundleRules struct {
	log   *deployLog
	rules map[string]catalogapi.BundleRule
	n     int
}

func (fakeBundleRules) RuleProblem(catalogapi.BundleRule) string { return "" }
func (f *fakeBundleRules) MatchingRule(context.Context, authn.Caller, catalogapi.BundleRule) (string, bool, error) {
	return "", false, nil
}
func (f *fakeBundleRules) RuleLive(_ context.Context, _ authn.Caller, id string) (bool, error) {
	_, ok := f.rules[id]
	return ok, nil
}
func (f *fakeBundleRules) CreateRule(_ context.Context, _ authn.Caller, r catalogapi.BundleRule) (string, error) {
	f.n++
	id := fmt.Sprintf("rule-%d", f.n)
	f.rules[id] = r
	f.log.add("create rule %s %s %s on %s:%s", id, r.Effect, r.Target, r.SubjectType, r.SubjectID)
	return id, nil
}
func (f *fakeBundleRules) UpdateRule(_ context.Context, _ authn.Caller, id string, r catalogapi.BundleRule, setEnabled bool) error {
	f.log.add("update rule %s enabled=%v", id, setEnabled)
	return nil
}
func (f *fakeBundleRules) DeleteRule(_ context.Context, _ authn.Caller, id string) error {
	delete(f.rules, id)
	f.log.add("delete rule %s", id)
	return nil
}

type fakeBundleMCPs struct{ catalogapi.BundleMCPs }

func (fakeBundleMCPs) ContextSecretLength() (minimum, maximum int) { return 16, 512 }
func (fakeBundleMCPs) CarriesSecretRef(any) bool                   { return false }

type deployFixture struct {
	log      *deployLog
	agents   *fakeBundleAgents
	triggers *fakeBundleTriggers
	rules    *fakeBundleRules
	admin    int
	mayEdit  bool
	w        *workspace
}

func newDeployFixture(t *testing.T) *deployFixture {
	f := &deployFixture{log: &deployLog{}, mayEdit: true}
	f.agents = &fakeBundleAgents{log: f.log, live: map[string]bool{}}
	f.triggers = &fakeBundleTriggers{log: f.log, triggers: map[string]catalogapi.BundleTrigger{}}
	f.rules = &fakeBundleRules{log: f.log, rules: map[string]catalogapi.BundleRule{}}
	b := &Bundles{d: BundleDeps{Agents: f.agents, MCPs: fakeBundleMCPs{}, Triggers: f.triggers, Rules: f.rules,
		Log:     slog.New(slog.DiscardHandler),
		Admin:   func(context.Context) error { f.admin++; return nil },
		MayEdit: func(context.Context, authn.Caller, string, string) (bool, error) { return f.mayEdit, nil }}}
	f.w = &workspace{b: b, c: authn.Caller{Principal: authn.Principal{UserID: "u"}, Workspace: ws(t)}, catalogs: map[string]*catalogMCP{}}
	return f
}

func (f *deployFixture) install(t *testing.T, b *Bundle, prior *priorInstall, approved ...entityRef) (*bundleInstaller, InstallResult, error) {
	t.Helper()
	ok := map[entityRef]bool{}
	for _, r := range approved {
		ok[r] = true
	}
	in := &bundleInstaller{w: f.w, approved: ok}
	res, err := in.install(context.Background(), b, demoValues(), prior, nil)
	return in, res, err
}

func actions(r InstallResult) []string {
	var out []string
	for _, e := range r.Entities {
		id := ""
		if e.ID != nil {
			id = *e.ID
		}
		out = append(out, fmt.Sprintf("%s:%s:%s:%s", e.Kind, e.Key, e.Action, id))
	}
	return out
}

func TestBundleInstallCreatesInDependencyOrder(t *testing.T) {
	f := newDeployFixture(t)
	b := mustParse(t, demoBundle)
	_, res, err := f.install(t, &b, nil)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"skill:s1:created:skill-1", "agent:agent:created:agent-2", "automation:daily:created:trigger-1", "policy:cap:created:rule-1"}
	if got := actions(res); !reflect.DeepEqual(got, want) {
		t.Fatalf("entities = %v, want %v", got, want)
	}
	if f.admin != 1 {
		t.Errorf("admin asked %d times, want 1", f.admin)
	}
	wantCalls := []string{
		"create skill Writer",
		"create agent Demo model=us-model skills=[skill-1]",
		`create cron demo:daily "Runs 0 9 * * * (UTC)" for agent-2 text=go`,
		"create rule rule-1 deny tool:web_search on agent:agent-2",
	}
	if !reflect.DeepEqual(f.log.calls, wantCalls) {
		t.Errorf("calls = %q", f.log.calls)
	}
	if res.Entities[1].Fingerprint == nil || *res.Entities[1].Fingerprint != "3fcb6f00ca46ec9bcb24f4066d586b97b988288d9297be0bfd75ff7557cd720c" {
		t.Errorf("agent fingerprint = %v", res.Entities[1].Fingerprint)
	}
	if got := res.SetupValues; !reflect.DeepEqual(got, wirejson.Object{{Key: "region", Value: "us"}}) {
		t.Errorf("remembered setup = %v (a secret is never remembered)", got)
	}
	if d := res.Entities[3].Detail; d == nil || *d != "deny tool:web_search on agent" {
		t.Errorf("policy detail = %v", d)
	}
}

func TestBundleInstallUndoesWhatItCreatedOnFailure(t *testing.T) {
	f := newDeployFixture(t)
	f.triggers.cronErr = errors.New("scheduler down")
	b := mustParse(t, demoBundle)
	_, _, err := f.install(t, &b, nil)
	if err == nil || err.Error() != "scheduler down" {
		t.Fatalf("err = %v", err)
	}
	tail := f.log.calls[len(f.log.calls)-2:]
	if !reflect.DeepEqual(tail, []string{"delete agent agent-2", "delete skill skill-1"}) {
		t.Fatalf("calls = %q", f.log.calls)
	}
}

func TestBundleInstallRefusesBlockedBundle(t *testing.T) {
	f := newDeployFixture(t)
	b := mustParse(t, demoBundle)
	in := &bundleInstaller{w: f.w, approved: map[entityRef]bool{}}
	_, err := in.install(context.Background(), &b, wirejson.Object{{Key: "region", Value: "us"}}, nil, nil)
	var be *BundleError
	if !errors.As(err, &be) || be.Kind != BundleInvalid || be.Msg != "package is not installable: missing required setup" ||
		len(be.Issues) != 1 || be.Issues[0].Message != "required setup field 'token' is missing" {
		t.Fatalf("err = %#v", err)
	}
	if len(f.log.calls) != 0 {
		t.Fatalf("wrote %q", f.log.calls)
	}
}

func redeploy(t *testing.T, f *deployFixture) (Bundle, *priorInstall) {
	t.Helper()
	first := mustParse(t, demoBundle)
	_, res, err := f.install(t, &first, nil)
	if err != nil {
		t.Fatal(err)
	}
	f.log.calls = nil
	changed := mustParse(t, strings.Replace(demoBundle, "instruction: be helpful", "instruction: be brief", 1))
	return changed, &priorInstall{bundle: first, result: res}
}

func TestBundleRedeployUpdatesApprovedAgentInPlace(t *testing.T) {
	f := newDeployFixture(t)
	b, prior := redeploy(t, f)
	in, res, err := f.install(t, &b, prior, entityRef{KindAgent, "agent"})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"skill:s1:unchanged:skill-1", "agent:agent:updated:agent-2", "automation:daily:unchanged:trigger-1", "policy:cap:unchanged:rule-1"}
	if got := actions(res); !reflect.DeepEqual(got, want) {
		t.Fatalf("entities = %v, want %v", got, want)
	}
	if !in.updatedInPlace || len(f.agents.updates) != 1 {
		t.Fatalf("updated in place = %v, updates %d", in.updatedInPlace, len(f.agents.updates))
	}
	u := f.agents.updates[0]
	if u.Instruction != "be brief" || !reflect.DeepEqual(u.SkillIDs, []string{"skill-1"}) || !reflect.DeepEqual(u.ManagedSkillIDs, []string{"skill-1"}) || u.SetReasoning || u.SetClient {
		t.Errorf("update = %+v", u)
	}
}

func TestBundleRedeployRefusesUnapprovedOrUneditableUpdate(t *testing.T) {
	f := newDeployFixture(t)
	b, prior := redeploy(t, f)
	_, _, err := f.install(t, &b, prior)
	var be *BundleError
	if !errors.As(err, &be) || be.Kind != BundleInstallFailed || be.Msg != "agent 'agent' would be updated, but the deploy plan did not approve it" {
		t.Fatalf("err = %#v", err)
	}
	f.mayEdit = false
	_, _, err = f.install(t, &b, prior, entityRef{KindAgent, "agent"})
	if !errors.As(err, &be) || be.Msg != "agent 'agent' would be updated, but you may not edit agent agent-2" ||
		len(be.Issues) != 1 || be.Issues[0].EntityKey == nil || *be.Issues[0].EntityKey != "agent" {
		t.Fatalf("err = %#v", err)
	}
	if len(f.agents.updates) != 0 {
		t.Fatalf("updated %d agents", len(f.agents.updates))
	}
}

func TestBundleRedeployFailureKeepsWhatItUpdated(t *testing.T) {
	f := newDeployFixture(t)
	b, prior := redeploy(t, f)
	b.Automations[0].Key = "weekly"
	f.triggers.cronErr = errors.New("scheduler down")
	in, _, err := f.install(t, &b, prior, entityRef{KindAgent, "agent"})
	if err == nil {
		t.Fatal("install succeeded")
	}
	for _, c := range f.log.calls {
		if strings.HasPrefix(c, "delete ") {
			t.Fatalf("deleted after an in-place update: %q", f.log.calls)
		}
	}
	partial, err := in.partialResult()
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"skill:s1:unchanged:skill-1", "agent:agent:updated:agent-2", "automation:daily:created:trigger-1", "policy:cap:created:rule-1"}
	if got := actions(partial); !reflect.DeepEqual(got, want) {
		t.Fatalf("partial = %v, want %v", got, want)
	}
}

func TestBundleRedeployRecordsOrphans(t *testing.T) {
	f := newDeployFixture(t)
	_, prior := redeploy(t, f)
	b := mustParse(t, demoBundle)
	b.Policies = nil
	_, res, err := f.install(t, &b, prior)
	if err != nil {
		t.Fatal(err)
	}
	last := res.Entities[len(res.Entities)-1]
	if last.Kind != KindPolicy || last.Action != ActionOrphaned || last.Detail == nil || *last.Detail != orphanedDetail || f.admin != 1 {
		t.Fatalf("last = %+v, admin %d", last, f.admin)
	}
}

// The hash and the issue are Python's: load_folder of the same files,
// sha256(json.dumps(bundle.model_dump(mode="json"), sort_keys=True)).
func TestLoadBundleFolderMatchesPython(t *testing.T) {
	files := StrPairs{
		{"agent.yaml", "\nname: researcher\ndisplay_name: Researcher\ndescription: Finds things out\nmodel: gpt-4o\ntoolsets: [agentarea/shell]\n" +
			"setup:\n  - {key: token, label: Token, type: secret, required: true}\n"},
		{"instructions.md", "Be thorough.\n"},
		{"skills/audit/SKILL.md", "---\nname: Site Audit\n---\n# Audit\n"},
		{"skills/plain/SKILL.md", "# Plain\n"},
		{"mcp/github.yaml", "name: GitHub\njson_spec: {type: command, command: npx, args: [-y, gh]}\nbindings: {GH_TOKEN: '${setup.token}'}\n"},
		{"schedules/daily.md", "---\ncron: '0 9 * * *'\ntimezone: Europe/Berlin\nenabled: true\n---\nWrite the morning report.\n"},
		{"channels/inbox.yaml", "type: telegram\nname: Inbox\nprompt: Answer it\n"},
		{"policies/no_email.yaml", "target: 'tool:send_email'\neffect: deny\n"},
		{"policies/budget.yaml", "subject: workspace\ntarget: spend\neffect: cap\nparams: {amount_usd: 5}\n"},
		{"README.md", "# hi"},
	}
	b, issues, err := LoadBundleFolder(files)
	if err != nil {
		t.Fatal(err)
	}
	got, err := sha256Dumps(b.Dump())
	if err != nil || got != "33d63b3c73e61717680b2f57a27e16c47609502ecf64fe70d81bab0ccdfa32b8" {
		t.Errorf("canonical hash = %s, %v", got, err)
	}
	if len(issues) != 1 || issues[0].Severity != SeverityWarn || issues[0].Message != "README.md: not part of the agent folder layout; not installed" || issues[0].EntityKey != nil {
		t.Errorf("issues = %+v", issues)
	}
}
