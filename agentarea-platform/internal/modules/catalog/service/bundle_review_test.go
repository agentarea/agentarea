package service

import (
	"context"
	"log/slog"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

func TestAgentKeyWorkspaceIsRefused(t *testing.T) {
	want := "agent key 'workspace' is reserved: a policy subject 'workspace' would mean the whole workspace; name the agent something else"
	if _, err := ParseBundle("name: x\nagents: [{key: workspace, name: W}]\n"); err == nil || !strings.Contains(err.Error(), want) {
		t.Fatalf("single-file: %v", err)
	}
	_, _, err := LoadBundleFolder(StrPairs{{"agentarea.yaml", "name: x\nschema_version: 1\nagents: {include: ./agents/*.md}\n"},
		{"agents/workspace.md", "---\nname: workspace\n---\nx\n"}})
	if err == nil || !strings.Contains(err.Error(), want) || !strings.HasPrefix(err.Error(), "agents/workspace.md:2: ") {
		t.Fatalf("folder: %v", err)
	}
}

func TestOriginGitRemoteLosesCredentialsQueryAndFragment(t *testing.T) {
	for in, want := range map[string]string{
		"https://user:tok3n@github.com/acme/bundles.git?ref=main#frag": "https://github.com/acme/bundles.git", // pragma: allowlist secret
		"https://github.com/acme/bundles.git":                          "https://github.com/acme/bundles.git",
		"ghp_x@github.com:acme/bundles.git":                            "github.com:acme/bundles.git",
		"git@github.com:acme/bundles.git?x=1#y":                        "github.com:acme/bundles.git",
		"ssh://git:pw@host:22/acme/b.git":                              "ssh://host:22/acme/b.git", // pragma: allowlist secret
	} {
		req, errs := ValidateAnalyzeRequest(wirejson.Object{{Key: "source", Value: "x"},
			{Key: "origin", Value: wirejson.Object{{Key: "git_remote", Value: in}}}})
		if errs != nil || *req.Target.Origin.GitRemote != want {
			t.Errorf("%s -> %v (%v), want %s", in, req.Target.Origin.GitRemote, errs, want)
		}
	}
}

func TestAnInvalidOtherInstallBlocksOnlyWhenItsNamesOverlap(t *testing.T) {
	b := mustParse(t, demoBundle)
	broken := func(name string) store.BundleResult {
		return store.BundleResult{ID: "inst-9", Name: "other", InstallResult: []byte(
			`{"bundle_name":"other","entities":[{"kind":"skill","key":"s","name":"` + name + `","action":"bogus","id":"skill-9"}]}`)}
	}
	others, issue, err := othersOf(context.Background(), slog.New(slog.DiscardHandler), []store.BundleResult{broken("Elsewhere")}, "", &b)
	if err != nil || issue != nil || len(others) != 0 {
		t.Fatalf("unrelated broken record: %v %+v %v", others, issue, err)
	}
	_, issue, err = othersOf(context.Background(), slog.New(slog.DiscardHandler), []store.BundleResult{broken("Writer")}, "", &b)
	if err != nil || issue == nil || issue.Severity != SeverityBlock || !strings.Contains(issue.Message, "install inst-9 ('other') no longer validates") {
		t.Fatalf("overlapping broken record: %+v %v", issue, err)
	}
}

// A delegates to B; B is renamed C. A's update names the tool it manages by B's agent id, so no stale B tool is left.
func TestRenamedDelegateIsManagedByItsAgentID(t *testing.T) {
	f := newDeployFixture(t)
	first := mustParse(t, "name: d\nagents:\n  - {key: a, name: A, model: us-model, delegates: [b]}\n  - {key: b, name: B, model: us-model}\n")
	_, res, err := f.install(t, &first, nil)
	if err != nil {
		t.Fatal(err)
	}
	renamed := mustParse(t, "name: d\nagents:\n  - {key: a, name: A, model: us-model, delegates: [c]}\n"+
		"  - {key: c, name: B, model: us-model, renamed_from: b}\n")
	if _, _, err := f.install(t, &renamed, &priorInstall{bundle: first, result: res}, entityRef{KindAgent, "a"}, entityRef{KindAgent, "c"}); err != nil {
		t.Fatal(err)
	}
	var forA *catalogapi.BundleAgentUpdate
	for i, u := range f.agents.updates {
		if u.Name == "A" {
			forA = &f.agents.updates[i]
		}
	}
	if forA == nil {
		t.Fatalf("a was not updated: %+v", f.agents.updates)
	}
	var managed []string
	for _, m := range forA.ManagedTools {
		if m.Type == "agent" {
			managed = append(managed, m.Name+"="+deref(m.AgentID))
		}
	}
	if len(forA.Tools) != 1 || forA.Tools[0].Name != "c" || *forA.Tools[0].AgentID != "agent-1" ||
		strings.Join(managed, ",") != "c=agent-1" {
		t.Fatalf("tools %+v, managed %v", forA.Tools, managed)
	}
}

func deref(s *string) string {
	if s == nil {
		return "<nil>"
	}
	return *s
}

const modelBundle = "name: m\nagents:\n  - {key: a, name: A, model: Team model}\n"

func modelFixture(t *testing.T, id string) (*deployFixture, *priorInstall) {
	t.Helper()
	f := newDeployFixture(t)
	f.w.b.d.ModelNames = fakeModelNames{instances: []modelsapi.InstanceName{{ID: id, Name: "Team model", ModelName: "m"}}}
	b := mustParse(t, modelBundle)
	_, res, err := f.install(t, &b, nil)
	if err != nil {
		t.Fatal(err)
	}
	if res.Entities[0].ModelID == nil || *res.Entities[0].ModelID != id {
		t.Fatalf("model id not recorded: %+v", res.Entities[0])
	}
	return f, &priorInstall{bundle: b, result: res}
}

func TestAModelNameNowNamingAnotherInstanceIsAnUpdate(t *testing.T) {
	const first, second = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
	f, prior := modelFixture(t, first)
	b := mustParse(t, modelBundle)
	if got := planned(analyzeWith(t, f, modelBundle, func(a *bundleAnalyzer) { a.prior = prior })); !reflect.DeepEqual(got, []string{"agent:a:unchanged"}) {
		t.Fatalf("same instance: %v", got)
	}
	f.w.models = nil
	f.w.b.d.ModelNames = fakeModelNames{instances: []modelsapi.InstanceName{{ID: second, Name: "Team model", ModelName: "m"}}}
	p := analyzeWith(t, f, modelBundle, func(a *bundleAnalyzer) { a.prior = prior })
	if got := planned(p); !reflect.DeepEqual(got, []string{"agent:a:will_update (model 'Team model' now names instance " + second + ")"}) {
		t.Fatalf("moved instance: %v", got)
	}
	_, res, err := f.install(t, &b, prior, entityRef{KindAgent, "a"})
	if err != nil || len(f.agents.updates) != 1 || f.agents.updates[0].ModelID != second || *res.Entities[0].ModelID != second {
		t.Fatalf("install: %v, updates %+v", err, f.agents.updates)
	}
}

// An agent the plan leaves unchanged is not resolved again at install: a model gone meanwhile does not fail it.
func TestAnUnchangedAgentIsNotResolvedAtInstall(t *testing.T) {
	const first = "11111111-1111-1111-1111-111111111111"
	f, prior := modelFixture(t, first)
	f.w.models = nil
	f.w.b.d.ModelNames = fakeModelNames{}
	b := mustParse(t, modelBundle)
	_, res, err := f.install(t, &b, prior)
	if err != nil || res.Entities[0].Action != ActionUnchanged || *res.Entities[0].ModelID != first {
		t.Fatalf("install: %v, %+v", err, res.Entities)
	}
}
