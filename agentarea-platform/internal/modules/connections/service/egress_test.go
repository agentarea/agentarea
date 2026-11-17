package service

import (
	"context"
	"errors"
	"slices"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

// fakeExits is governance's require_bindable over a set of exit ids.
type fakeExits struct {
	known  map[string]bool
	denied bool
	asked  []string
}

func (f *fakeExits) RequireBindable(_ context.Context, _ authn.Caller, exitID string) error {
	f.asked = append(f.asked, exitID)
	if f.denied {
		return authz.ErrDenied
	}
	if !f.known[exitID] {
		return &governanceapi.EgressExitNotFoundError{ID: exitID}
	}
	return nil
}

func enterprise(f *instFixture, known ...string) *fakeExits {
	exits := &fakeExits{known: map[string]bool{}}
	for _, k := range known {
		exits.known[k] = true
	}
	f.svc.d.EgressExits = exits
	return exits
}

func refusal(t *testing.T, err error) string {
	t.Helper()
	var si *domain.SpecInvalid
	if !errors.As(err, &si) || len(si.Errors) != 1 {
		t.Fatalf("err = %v, want one refusal", err)
	}
	return si.Errors[0]
}

func imageSpec(t *testing.T, f *instFixture, jsonSpec map[string]any) string {
	t.Helper()
	img := "ghcr.io/acme/mcp:1"
	return f.spec(t, catalogapi.MCPSpec{Name: "img", DockerImageURL: &img, JSONSpec: jsonSpec})
}

func TestAnInstanceBindsAnExitTheEditionLetsItUse(t *testing.T) {
	f := newInstFixture(t)
	exit := uuid.NewString()
	exits := enterprise(f, exit)
	v, err := f.svc.CreateInstance(context.Background(), f.c, InstanceCreate{Name: "x", ServerSpecID: imageSpec(t, f, nil),
		JSONSpec: map[string]any{domain.EgressExitSpecKey: exit}})
	if err != nil {
		t.Fatal(err)
	}
	if v.Instance.JSONSpec[domain.EgressExitSpecKey] != exit || !slices.Equal(exits.asked, []string{exit}) {
		t.Fatalf("stored %v, asked %v", v.Instance.JSONSpec, exits.asked)
	}
}

func TestAnInstanceAskingForAnExitItCannotHaveIsToldWhy(t *testing.T) {
	f := newInstFixture(t)
	enterprise(f)
	gone := uuid.NewString()
	_, err := f.svc.CreateInstance(context.Background(), f.c, InstanceCreate{Name: "x", ServerSpecID: imageSpec(t, f, nil),
		JSONSpec: map[string]any{domain.EgressExitSpecKey: gone}})
	if got := refusal(t, err); got != "Egress exit "+gone+" not found" {
		t.Fatalf("refusal %q", got)
	}

	enterprise(f).denied = true
	_, err = f.svc.CreateInstance(context.Background(), f.c, InstanceCreate{Name: "y", ServerSpecID: imageSpec(t, f, nil),
		JSONSpec: map[string]any{domain.EgressExitSpecKey: gone}})
	if !errors.Is(err, authz.ErrDenied) {
		t.Fatalf("an exit the caller may not use: %v", err)
	}
}

func TestAnInstanceRebindingAnExitIsCheckedAndOneKeepingItIsNot(t *testing.T) {
	f := newInstFixture(t)
	first, second := uuid.NewString(), uuid.NewString()
	exits := enterprise(f, first, second)
	ctx := context.Background()
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "x", ServerSpecID: imageSpec(t, f, nil),
		JSONSpec: map[string]any{domain.EgressExitSpecKey: first}})
	if err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(v.Instance.ID)
	if _, err := f.svc.UpdateInstance(ctx, f.c, id, InstancePatchIn{JSONSpec: map[string]any{domain.EgressExitSpecKey: first}}); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.UpdateInstance(ctx, f.c, id, InstancePatchIn{JSONSpec: map[string]any{domain.EgressExitSpecKey: second}}); err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(exits.asked, []string{first, second}) {
		t.Fatalf("asked %v", exits.asked)
	}
	exits.known = map[string]bool{}
	_, err = f.svc.UpdateInstance(ctx, f.c, id, InstancePatchIn{JSONSpec: map[string]any{domain.EgressExitSpecKey: first}})
	if got := refusal(t, err); got != "Egress exit "+first+" not found" {
		t.Fatalf("refusal %q", got)
	}
}

func TestAnInstanceInheritsTheRequirementItsSpecDeclares(t *testing.T) {
	f := newInstFixture(t)
	required := map[string]any{domain.EgressSpecKey: map[string]any{"required": true}}
	specID := imageSpec(t, f, required)
	_, err := f.svc.CreateInstance(context.Background(), f.c, InstanceCreate{Name: "oss", ServerSpecID: specID})
	if got := refusal(t, err); got != domain.EgressExitsUnsupported {
		t.Fatalf("open core: %q", got)
	}
	enterprise(f)
	v, err := f.svc.CreateInstance(context.Background(), f.c, InstanceCreate{Name: "ent", ServerSpecID: specID})
	if err != nil {
		t.Fatal(err)
	}
	if _, has := v.Instance.JSONSpec[domain.EgressSpecKey]; has {
		t.Fatalf("the instance stored its spec's requirement: %v", v.Instance.JSONSpec)
	}
}

func TestASpecRequiringAnExitIsStoredOnlyWhereExitsExist(t *testing.T) {
	f := newInstFixture(t)
	img := "ghcr.io/acme/browser:1"
	required := map[string]any{domain.EgressSpecKey: map[string]any{"required": true}}
	n := catalogapi.MCPSpecNew{Name: "browser", DockerImageURL: &img, JSONSpec: required}
	_, err := f.svc.CreateSpec(context.Background(), f.c, n)
	if got := refusal(t, err); got != domain.EgressExitsUnsupported {
		t.Fatalf("open core: %q", got)
	}
	notRequired := n
	notRequired.JSONSpec = map[string]any{domain.EgressSpecKey: map[string]any{"required": false}}
	if _, err := f.svc.CreateSpec(context.Background(), f.c, notRequired); err != nil {
		t.Fatalf("a spec needing no exit needs no edition: %v", err)
	}
	enterprise(f)
	sp, err := f.svc.CreateSpec(context.Background(), f.c, n)
	if err != nil {
		t.Fatal(err)
	}
	if e, _ := sp.JSONSpec[domain.EgressSpecKey].(map[string]any); e["required"] != true {
		t.Fatalf("stored %v", sp.JSONSpec)
	}
}
