package service

import (
	"context"
	"errors"
	"log/slog"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
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
		Models: noModels{}, Log: slog.New(slog.DiscardHandler),
		Admin:   func(context.Context) error { return nil },
		MayEdit: func(context.Context, authn.Caller, string, string) (bool, error) { return true, nil }})
	if err != nil {
		t.Fatal(err)
	}
	ctx := authn.WithCaller(context.Background(), authn.Caller{Principal: authn.Principal{UserID: "u"}, Workspace: w})

	first, err := b.AnalyzeText(ctx, demoBundle, demoValues())
	if err != nil {
		t.Fatal(err)
	}
	res, err := b.Install(ctx, first.Bundle, demoValues(), *first.PlanDigest)
	if err != nil {
		t.Fatal(err)
	}
	if res.InstalledBundleID == nil {
		t.Fatal("no installed_bundle_id")
	}

	again, err := b.AnalyzeText(ctx, demoBundle, demoValues())
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range again.Entities {
		if e.Status != StatusUnchanged {
			t.Errorf("replan %s:%s = %s", e.Kind, e.Key, e.Status)
		}
	}

	changed, err := b.AnalyzeText(ctx, strings.Replace(demoBundle, "be helpful", "be brief", 1), demoValues())
	if err != nil {
		t.Fatal(err)
	}
	_, err = b.Install(ctx, changed.Bundle, demoValues(), *first.PlanDigest)
	var be *BundleError
	if !errors.As(err, &be) || be.Kind != BundlePlanChanged {
		t.Fatalf("stale digest: %v", err)
	}
	updated, err := b.Install(ctx, changed.Bundle, demoValues(), *changed.PlanDigest)
	if err != nil {
		t.Fatal(err)
	}
	if *updated.InstalledBundleID != *res.InstalledBundleID || updated.Entities[1].Action != ActionUpdated || len(f.agents.updates) != 1 {
		t.Fatalf("redeploy = %+v", updated)
	}
}
