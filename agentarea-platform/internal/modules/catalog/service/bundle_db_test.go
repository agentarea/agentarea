package service

import (
	"context"
	"errors"
	"log/slog"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

type noModels struct{}

func (noModels) Model(context.Context, modelsapi.Principal, string) (modelsapi.ResolvedModel, error) {
	return modelsapi.ResolvedModel{}, modelsapi.ErrNotFound
}

func TestBundleInstallRecordsAndRedeploysByDigest(t *testing.T) {
	pools := openSyncDB(t)
	f := newDeployFixture(t)
	id := "bt-" + uuid.NewString()[:8]
	w, err := scope.NewWorkspace(id, id)
	if err != nil {
		t.Fatal(err)
	}
	b, err := NewBundles(BundleDeps{DB: pools, Agents: f.agents, MCPs: fakeBundleMCPs{}, Triggers: f.triggers, Rules: f.rules,
		Models: noModels{}, ModelNames: demoModels(), Log: slog.New(slog.DiscardHandler),
		Admin:   func(context.Context) error { return nil },
		MayEdit: func(context.Context, authn.Caller, string, string) (bool, error) { return true, nil }})
	if err != nil {
		t.Fatal(err)
	}
	ctx := authn.WithCaller(context.Background(), authn.Caller{Principal: authn.Principal{UserID: "u"}, Workspace: w})

	first, err := b.AnalyzeText(ctx, demoBundle, demoValues(), BundleTarget{})
	if err != nil {
		t.Fatal(err)
	}
	res, err := b.Install(ctx, first.Bundle, demoValues(), *first.PlanDigest, BundleTarget{})
	if err != nil {
		t.Fatal(err)
	}
	if res.InstalledBundleID == nil {
		t.Fatal("no installed_bundle_id")
	}

	into := BundleTarget{Into: res.InstalledBundleID}
	again, err := b.AnalyzeText(ctx, demoBundle, demoValues(), into)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range again.Entities {
		if e.Status != StatusUnchanged {
			t.Errorf("replan %s:%s = %s", e.Kind, e.Key, e.Status)
		}
	}

	changed, err := b.AnalyzeText(ctx, strings.Replace(demoBundle, "be helpful", "be brief", 1), demoValues(), into)
	if err != nil {
		t.Fatal(err)
	}
	_, err = b.Install(ctx, changed.Bundle, demoValues(), *first.PlanDigest, into)
	var be *BundleError
	if !errors.As(err, &be) || be.Kind != BundlePlanChanged {
		t.Fatalf("stale digest: %v", err)
	}
	updated, err := b.Install(ctx, changed.Bundle, demoValues(), *changed.PlanDigest, into)
	if err != nil {
		t.Fatal(err)
	}
	if *updated.InstalledBundleID != *res.InstalledBundleID || updated.Entities[1].Action != ActionUpdated || len(f.agents.updates) != 1 {
		t.Fatalf("redeploy = %+v", updated)
	}
}

func newDBBundles(t *testing.T) (*Bundles, *deployFixture, context.Context) {
	t.Helper()
	pools := openSyncDB(t)
	f := newDeployFixture(t)
	id := "bt-" + uuid.NewString()[:8]
	w, err := scope.NewWorkspace(id, id)
	if err != nil {
		t.Fatal(err)
	}
	b, err := NewBundles(BundleDeps{DB: pools, Agents: f.agents, MCPs: fakeBundleMCPs{}, Triggers: f.triggers, Rules: f.rules,
		Models: noModels{}, ModelNames: demoModels(), Log: slog.New(slog.DiscardHandler),
		Admin:   func(context.Context) error { return nil },
		MayEdit: func(context.Context, authn.Caller, string, string) (bool, error) { return true, nil }})
	if err != nil {
		t.Fatal(err)
	}
	return b, f, authn.WithCaller(context.Background(), authn.Caller{Principal: authn.Principal{UserID: "u"}, Workspace: w})
}

func issueCode(p ImportPreview) string {
	for _, i := range p.Issues {
		if i.Code != nil {
			return *i.Code
		}
	}
	return ""
}

func TestBundleInstallIsFoundByIDNotByName(t *testing.T) {
	b, _, ctx := newDBBundles(t)
	analyze := func(src string, target BundleTarget) ImportPreview {
		t.Helper()
		p, err := b.AnalyzeText(ctx, src, demoValues(), target)
		if err != nil {
			t.Fatal(err)
		}
		return p
	}
	first := analyze(demoBundle, BundleTarget{})
	if first.Install != nil || first.ExistingInstall != nil || !first.Installable {
		t.Fatalf("first plan = %+v", first)
	}
	commit := "abc123"
	res, err := b.Install(ctx, first.Bundle, demoValues(), *first.PlanDigest, BundleTarget{Origin: &BundleOrigin{GitCommit: &commit}})
	if err != nil {
		t.Fatal(err)
	}
	id := *res.InstalledBundleID

	taken := analyze(demoBundle, BundleTarget{})
	if taken.Installable || taken.PlanDigest != nil || issueCode(taken) != CodeBundleExists || taken.ExistingInstall == nil ||
		taken.ExistingInstall.ID != id || taken.ExistingInstall.CreatedBy != "u" || *taken.ExistingInstall.UpdatedBy != "u" {
		t.Fatalf("plan for a taken name = %+v", taken)
	}
	if _, err := b.Install(ctx, first.Bundle, demoValues(), *first.PlanDigest, BundleTarget{}); !isPlanChanged(err) {
		t.Fatalf("install over a taken name: %v", err)
	}

	for _, into := range []string{id, "demo"} {
		p := analyze(demoBundle, BundleTarget{Into: &into})
		if !p.Installable || p.Install == nil || p.Install.ID != id || *p.Install.UpdatedBy != "u" {
			t.Fatalf("plan into %s = %+v", into, p)
		}
		if o, ok := p.Install.Origin.(wirejson.Object); !ok || mustJSON(t, o) != `{"git_commit":"abc123"}` {
			t.Fatalf("origin = %#v", p.Install.Origin)
		}
	}
	gone := uuid.NewString()
	if p := analyze(demoBundle, BundleTarget{Into: &gone}); issueCode(p) != CodeInstallNotFound ||
		p.Issues[0].Message != "bundle install "+gone+" not found; it was deleted — deploy without --into to create it again" {
		t.Fatalf("plan into a deleted install = %+v", p.Issues)
	}

	into := BundleTarget{Into: &id}
	stale := analyze(demoBundle, into)
	if _, err := b.Install(ctx, stale.Bundle, demoValues(), *stale.PlanDigest, into); err != nil {
		t.Fatal(err)
	}
	if _, err := b.Install(ctx, stale.Bundle, demoValues(), *stale.PlanDigest, into); !isPlanChanged(err) {
		t.Fatalf("install over a newer revision: %v", err)
	}

	renamed := analyze(strings.Replace(demoBundle, "name: demo\n", "name: demo-renamed\n", 1), into)
	if _, err := b.Install(ctx, renamed.Bundle, demoValues(), *renamed.PlanDigest, into); err != nil {
		t.Fatal(err)
	}
	if p := analyze(strings.Replace(demoBundle, "name: demo\n", "name: demo-renamed\n", 1), BundleTarget{}); issueCode(p) != CodeBundleExists ||
		p.ExistingInstall.ID != id {
		t.Fatalf("renamed install not found by its new name: %+v", p.Issues)
	}
	copied := analyze(demoBundle, BundleTarget{})
	if copied.Installable || len(copied.Issues) == 0 || !strings.Contains(copied.Issues[0].Message, "belongs to bundle 'demo-renamed'") {
		t.Fatalf("a second bundle took the first one's skill: %+v", copied.Issues)
	}
}

func isPlanChanged(err error) bool {
	var be *BundleError
	return errors.As(err, &be) && be.Kind == BundlePlanChanged
}
