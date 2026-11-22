package service

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

// namedCatalog is the workspace secrets by name.
type namedCatalog struct {
	memCatalog
	names map[string]string
}

func (n *namedCatalog) GetNamedForUse(_ context.Context, name string) (ksecrets.Secret, error) {
	id, ok := n.names[name]
	if !ok {
		return ksecrets.Secret{}, &ksecrets.NotFoundError{Message: name}
	}
	return ksecrets.Secret{ID: id, Name: name}, nil
}

func bundleOpenAPIFixture(t *testing.T) (*writesFixture, BundleOpenAPIs) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	catalog := &namedCatalog{names: map[string]string{"crm_token": uuid.NewString()}}
	f.svc.d.Catalog = func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return catalog }
	f.secrets.values["crm_token"] = "Bearer t0k"
	return f, BundleOpenAPIs{S: func() *Service { return f.svc }}
}

func petSpec(t *testing.T) catalogapi.BundleOpenAPISpec {
	return catalogapi.BundleOpenAPISpec{Name: "pets", BaseURL: "https://api.example.com/{tenant}", Spec: writesSpecOf(t, writesPetSpec),
		Headers:   []catalogapi.BundleOpenAPIParam{{Name: "Authorization", SecretName: textPtr("crm_token")}, {Name: "Accept", Value: "application/json"}},
		Query:     []catalogapi.BundleOpenAPIParam{{Name: "key", Value: "q1", Secret: true}, {Name: "fmt", Value: "json"}},
		Variables: []catalogapi.BundleOpenAPIParam{{Name: "tenant", Value: "acme"}}}
}

func TestBundleOpenAPICreatesWithTheSecretsItNames(t *testing.T) {
	f, b := bundleOpenAPIFixture(t)
	ctx := context.Background()
	if problem, err := b.OpenAPIProblem(ctx, f.caller, petSpec(t)); problem != "" || err != nil {
		t.Fatalf("problem = %q, %v", problem, err)
	}
	id, err := b.CreateOpenAPI(ctx, f.caller, petSpec(t))
	if err != nil {
		t.Fatal(err)
	}
	if f.secrets.values[domain.SecretHeaderKey(id, "Authorization")] != "Bearer t0k" || f.secrets.values[domain.SecretQueryKey(id, "key")] != "q1" ||
		f.secrets.values[domain.SecretURLVarKey(id, "tenant")] != "acme" {
		t.Fatalf("secrets = %v", f.secrets.values)
	}
	conn := f.conns.rows[uuid.MustParse(id)]
	if len(conn.AvailableTools) != 2 {
		t.Fatalf("tools = %+v", conn.AvailableTools)
	}
	if name, ok, err := b.ConnectionName(ctx, f.caller, id); !ok || err != nil || name != "pets" {
		t.Fatalf("name = %q %v %v", name, ok, err)
	}

	changed := petSpec(t)
	changed.Query = []catalogapi.BundleOpenAPIParam{{Name: "key", Keep: true, Secret: true}, {Name: "fmt", Value: "xml"}}
	changed.Variables = []catalogapi.BundleOpenAPIParam{{Name: "tenant", Keep: true}}
	f.graph.allowed[f.caller.GraphSubject()+"#"+id] = true
	if err := b.UpdateOpenAPI(ctx, f.caller, id, changed); err != nil {
		t.Fatal(err)
	}
	if f.secrets.values[domain.SecretQueryKey(id, "key")] != "q1" || f.secrets.values[domain.SecretURLVarKey(id, "tenant")] != "acme" {
		t.Fatalf("kept secrets = %v", f.secrets.values)
	}
	conn = f.conns.rows[uuid.MustParse(id)]
	if q := conn.CustomQuery; len(q) != 2 || *q[1].Value != "xml" {
		t.Fatalf("query = %+v", q)
	}
}

func TestBundleOpenAPIRefusesWhatTheRoutesRefuse(t *testing.T) {
	f, b := bundleOpenAPIFixture(t)
	ctx := context.Background()
	missing := petSpec(t)
	missing.Headers[0].SecretName = textPtr("nope")
	if problem, err := b.OpenAPIProblem(ctx, f.caller, missing); err != nil || problem != "Secret 'nope' is not a secret of this workspace" {
		t.Fatalf("problem = %q, %v", problem, err)
	}
	unbound := petSpec(t)
	unbound.Variables = nil
	if problem, err := b.OpenAPIProblem(ctx, f.caller, unbound); err != nil || problem == "" {
		t.Fatalf("a base URL variable with no value: %q, %v", problem, err)
	}
	_, err := b.CreateOpenAPI(ctx, f.caller, missing)
	var refusal *catalogapi.BundleRefusal
	if !errors.As(err, &refusal) || len(f.conns.rows) != 0 {
		t.Fatalf("err = %v, rows = %d", err, len(f.conns.rows))
	}
	if !b.HeaderIsSecret("Authorization") || b.HeaderIsSecret("accept") {
		t.Fatal("header classification differs from the connection's")
	}
}

func textPtr(s string) *string { return &s }
