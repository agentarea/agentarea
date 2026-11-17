package service

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/store"
)

type fakeExits struct {
	row     domain.EgressExit
	created []domain.EgressExit
	updated store.EgressExitChanges
	deleted bool
}

func (f *fakeExits) List(context.Context, db.Session) ([]domain.EgressExit, error) {
	return []domain.EgressExit{f.row}, nil
}

func (f *fakeExits) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.EgressExit, bool, error) {
	if id.String() != f.row.ID {
		return domain.EgressExit{}, false, nil
	}
	return f.row, true, nil
}

func (f *fakeExits) Create(_ context.Context, s db.Session, e domain.EgressExit, now time.Time) (domain.EgressExit, error) {
	e.WorkspaceID, e.CreatedAt, e.UpdatedAt = s.Workspace().ID(), now, now
	f.created = append(f.created, e)
	return e, nil
}

func (f *fakeExits) Update(_ context.Context, _ db.Session, id uuid.UUID, ch store.EgressExitChanges, _ time.Time) (domain.EgressExit, bool, error) {
	if id.String() != f.row.ID {
		return domain.EgressExit{}, false, nil
	}
	f.updated = ch
	for k, v := range ch {
		switch k {
		case "description":
			f.row.Description = v.(*string)
		case "upstream_url":
			f.row.UpstreamURL = v.(*string)
		case "username":
			f.row.Username = v.(*string)
		}
	}
	return f.row, true, nil
}

func (f *fakeExits) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	f.deleted = id.String() == f.row.ID
	return f.deleted, nil
}

type fakeBindings struct {
	bound   []connectionsapi.EgressBoundInstance
	retired []string
}

func (f *fakeBindings) BoundToEgressExit(context.Context, scope.Workspace, string) ([]connectionsapi.EgressBoundInstance, error) {
	return f.bound, nil
}

func (f *fakeBindings) RetireBeforeMutation(_ context.Context, id string) error {
	f.retired = append(f.retired, id)
	return nil
}

type egressGraph struct {
	authz.Graph
	allow   bool
	checked []string
	writes  []authz.Tuple
	revoked bool
}

func (g *egressGraph) Check(_ context.Context, _, relation, _, id string) (bool, error) {
	g.checked = append(g.checked, relation+" "+id)
	return g.allow, nil
}

func (g *egressGraph) Read(context.Context, authz.Query) ([]authz.Tuple, error) {
	g.revoked = true
	return nil, nil
}

func (g *egressGraph) Write(_ context.Context, writes, _ []authz.Tuple) error {
	g.writes = append(g.writes, writes...)
	return nil
}

type egressCatalog struct {
	secrets.Catalog
	staged [][]secrets.Reference
	use    error
}

func (c *egressCatalog) GetForUse(_ context.Context, id string) (secrets.Secret, error) {
	return secrets.Secret{ID: id}, c.use
}

func (c *egressCatalog) StageReferences(_ context.Context, _ db.Session, consumerType, _ string, refs []secrets.Reference) error {
	if consumerType != "egress_exit" {
		return errors.New("staged for " + consumerType)
	}
	c.staged = append(c.staged, refs)
	return nil
}

type egressFixture struct {
	fixture
	exits    *fakeExits
	bindings *fakeBindings
	graph    *egressGraph
	catalog  *egressCatalog
	refused  error
}

func ptr[T any](v T) *T { return &v }

func ownRow() domain.EgressExit {
	return domain.EgressExit{ID: uuid.NewString(), Name: "office", UpstreamURL: ptr("https://proxy.example.com:443"), CreatedBy: "member"}
}

func newEgressFixture(t *testing.T, row domain.EgressExit, bound ...connectionsapi.EgressBoundInstance) *egressFixture {
	t.Helper()
	f := &egressFixture{fixture: newFixture(t), exits: &fakeExits{row: row}, bindings: &fakeBindings{bound: bound},
		graph: &egressGraph{allow: true}, catalog: &egressCatalog{}}
	f.sv = New(Deps{DB: fakeDB{}, Policies: f.rules, Audit: f.audit, Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
		Secrets: func(scope.Workspace, secrets.Actor, secrets.Auditor) secrets.Catalog { return f.catalog },
		EgressExits: &EgressExitPorts{Store: f.exits, Graph: f.graph, Instances: f.bindings,
			Upstream: func(context.Context, string) error { return f.refused }}})
	return f
}

func mustID(t *testing.T, s string) uuid.UUID {
	t.Helper()
	return uuid.MustParse(s)
}

func TestAnExitInstancesLeaveThroughIsNotDeletedUnderThem(t *testing.T) {
	row := ownRow()
	f := newEgressFixture(t, row, connectionsapi.EgressBoundInstance{ID: uuid.NewString(), Name: "zeta", Transport: "docker"},
		connectionsapi.EgressBoundInstance{ID: uuid.NewString(), Name: "alpha", Transport: "url"})
	err := f.sv.DeleteEgressExit(context.Background(), f.caller, mustID(t, row.ID))
	var inUse *EgressExitInUseError
	if !errors.As(err, &inUse) || inUse.Error() != "2 MCP instance(s) leave through this exit (alpha, zeta); unbind them before deleting it" {
		t.Fatalf("err = %v", err)
	}
	if f.exits.deleted || len(f.audit.events) != 0 {
		t.Fatal("deleted under its instances")
	}
}

func TestAPlatformExitIsNeverChanged(t *testing.T) {
	row := domain.EgressExit{ID: uuid.NewString(), Name: "hop", Via: ptr("hop-a"), ManagedBy: ptr(domain.ManagedByPlatform)}
	f := newEgressFixture(t, row)
	want := "Egress exit " + row.ID + " is the platform's; it is not changed through the API"
	_, err := f.sv.UpdateEgressExit(context.Background(), f.caller, mustID(t, row.ID), EgressExitPatch{"description": ptr("mine now")})
	var forbidden *EgressExitForbiddenError
	if !errors.As(err, &forbidden) || forbidden.Error() != want {
		t.Fatalf("update: %v", err)
	}
	err = f.sv.DeleteEgressExit(context.Background(), f.caller, mustID(t, row.ID))
	if !errors.As(err, &forbidden) {
		t.Fatalf("delete: %v", err)
	}
	if f.exits.updated != nil || f.exits.deleted {
		t.Fatal("the platform exit changed")
	}
}

func TestANewRouteRestartsTheRunningInstancesBeforeItIsStored(t *testing.T) {
	row := ownRow()
	docker := connectionsapi.EgressBoundInstance{ID: uuid.NewString(), Name: "d", Transport: "docker"}
	command := connectionsapi.EgressBoundInstance{ID: uuid.NewString(), Name: "c", Transport: "command"}
	f := newEgressFixture(t, row, docker, connectionsapi.EgressBoundInstance{ID: uuid.NewString(), Name: "u", Transport: "url"}, command)
	e, err := f.sv.UpdateEgressExit(context.Background(), f.caller, mustID(t, row.ID), EgressExitPatch{"upstream_url": ptr("https://other.example.com:443")})
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(f.bindings.retired, []string{docker.ID, command.ID}) {
		t.Fatalf("retired %v", f.bindings.retired)
	}
	if len(f.exits.updated) != 1 || *f.exits.updated["upstream_url"].(*string) != "https://other.example.com:443" || *e.UpstreamURL != "https://other.example.com:443" {
		t.Fatalf("updated %v", f.exits.updated)
	}
	ev := f.audit.events[0]
	if ev.Action != "egress_exit.update" || ev.ResourceType != "egress_exit" || *ev.ResourceID != row.ID ||
		len(ev.Changes) != 1 || ev.Changes[0]["field"] != "upstream_url" {
		t.Fatalf("audit %+v", ev)
	}
}

func TestANewDescriptionRestartsNothing(t *testing.T) {
	row := ownRow()
	f := newEgressFixture(t, row, connectionsapi.EgressBoundInstance{ID: uuid.NewString(), Name: "d", Transport: "docker"})
	if _, err := f.sv.UpdateEgressExit(context.Background(), f.caller, mustID(t, row.ID), EgressExitPatch{"description": ptr("the office proxy")}); err != nil {
		t.Fatal(err)
	}
	if len(f.bindings.retired) != 0 || len(f.exits.updated) != 1 || *f.exits.updated["description"].(*string) != "the office proxy" {
		t.Fatalf("retired %v updated %v", f.bindings.retired, f.exits.updated)
	}
}

func TestAnUnchangedPatchStoresNothingAndIsAudited(t *testing.T) {
	row := ownRow()
	f := newEgressFixture(t, row)
	if _, err := f.sv.UpdateEgressExit(context.Background(), f.caller, mustID(t, row.ID), EgressExitPatch{"name": ptr("office")}); err != nil {
		t.Fatal(err)
	}
	if f.exits.updated != nil || len(f.audit.events) != 1 || f.audit.events[0].Changes == nil || len(f.audit.events[0].Changes) != 0 {
		t.Fatalf("updated %v audit %+v", f.exits.updated, f.audit.events)
	}
}

func TestAnExitCannotLoseWhereItLeads(t *testing.T) {
	row := ownRow()
	f := newEgressFixture(t, row)
	_, err := f.sv.UpdateEgressExit(context.Background(), f.caller, mustID(t, row.ID), EgressExitPatch{"upstream_url": (*string)(nil)})
	var invalid *EgressExitInvalidError
	if !errors.As(err, &invalid) || invalid.Error() != "upstream_url cannot be cleared" || f.exits.updated != nil {
		t.Fatalf("err = %v", err)
	}
}

func TestCredentialsAddedToAPlaintextProxyAreRefused(t *testing.T) {
	row := ownRow()
	row.UpstreamURL = ptr("http://proxy.example.com:3128")
	f := newEgressFixture(t, row)
	_, err := f.sv.UpdateEgressExit(context.Background(), f.caller, mustID(t, row.ID), EgressExitPatch{"username": ptr("u")})
	var invalid *EgressExitInvalidError
	if !errors.As(err, &invalid) || !strings.Contains(invalid.Error(), "unencrypted") || f.exits.updated != nil {
		t.Fatalf("err = %v", err)
	}
}

func TestAnUpstreamThisDeploymentMayNotReachIsRefused(t *testing.T) {
	f := newEgressFixture(t, ownRow())
	f.refused = &netguard.BlockedError{Host: "10.0.0.1"}
	_, err := f.sv.CreateEgressExit(context.Background(), f.caller, EgressExitNew{Name: "lan", UpstreamURL: "http://10.0.0.1:3128"})
	var invalid *EgressExitInvalidError
	if !errors.As(err, &invalid) || invalid.Error() != "upstream_url must be a public address this deployment may reach" || len(f.exits.created) != 0 {
		t.Fatalf("err = %v", err)
	}
}

func TestACreatedExitIsItsCreatorsAndAudited(t *testing.T) {
	f := newEgressFixture(t, ownRow())
	secret := uuid.NewString()
	e, err := f.sv.CreateEgressExit(context.Background(), f.caller, EgressExitNew{Name: "home", UpstreamURL: "https://p.example.com:443",
		Username: ptr("u"), PasswordSecretID: &secret})
	if err != nil {
		t.Fatal(err)
	}
	if e.CreatedBy != "owner" || e.WorkspaceID != f.ws.ID() || *e.PasswordSecretID != secret || e.ManagedBy != nil {
		t.Fatalf("created %+v", e)
	}
	if len(f.catalog.staged) != 1 || !slices.Equal(f.catalog.staged[0], []secrets.Reference{{SecretID: secret, Field: "password"}}) {
		t.Fatalf("staged %v", f.catalog.staged)
	}
	owned := false
	for _, w := range f.graph.writes {
		owned = owned || (w.Object == authz.ObjectRef(authz.TypeResource, e.ID) && w.User == f.caller.GraphSubject())
	}
	if !owned {
		t.Fatalf("not granted: %v", f.graph.writes)
	}
	if ev := f.audit.events[0]; ev.Action != "egress_exit.create" || *ev.ResourceID != e.ID || ev.Changes != nil {
		t.Fatalf("audit %+v", ev)
	}
}

func TestAPasswordTheCallerMayNotUseIsRefused(t *testing.T) {
	f := newEgressFixture(t, ownRow())
	in := EgressExitNew{Name: "home", UpstreamURL: "https://p.example.com:443", Username: ptr("u"), PasswordSecretID: ptr(uuid.NewString())}
	f.catalog.use = &secrets.NotFoundError{Message: "Secret gone not found"}
	var invalid *EgressExitInvalidError
	if _, err := f.sv.CreateEgressExit(context.Background(), f.caller, in); !errors.As(err, &invalid) || invalid.Error() != "Secret gone not found" {
		t.Fatalf("missing secret: %v", err)
	}
	f.catalog.use = &secrets.AccessDeniedError{Message: "no"}
	var forbidden *EgressExitForbiddenError
	if _, err := f.sv.CreateEgressExit(context.Background(), f.caller, in); !errors.As(err, &forbidden) || forbidden.Error() != "no" {
		t.Fatalf("denied secret: %v", err)
	}
	if len(f.exits.created) != 0 {
		t.Fatal("created with a refused password")
	}
}

func TestADeletedExitLeavesTheGraphAndItsReference(t *testing.T) {
	row := ownRow()
	f := newEgressFixture(t, row)
	if err := f.sv.DeleteEgressExit(context.Background(), f.caller, mustID(t, row.ID)); err != nil {
		t.Fatal(err)
	}
	if !f.exits.deleted || !f.graph.revoked || len(f.catalog.staged) != 1 || len(f.catalog.staged[0]) != 0 {
		t.Fatalf("deleted %v revoked %v staged %v", f.exits.deleted, f.graph.revoked, f.catalog.staged)
	}
	if ev := f.audit.events[0]; ev.Action != "egress_exit.delete" || *ev.ResourceID != row.ID {
		t.Fatalf("audit %+v", ev)
	}
}

func TestAPlatformExitBindsWithoutAGrantAndAnOwnOneNeedsUse(t *testing.T) {
	platform := domain.EgressExit{ID: uuid.NewString(), Name: "hop", Via: ptr("hop-a"), ManagedBy: ptr(domain.ManagedByPlatform)}
	f := newEgressFixture(t, platform)
	f.graph.allow = false
	if err := f.sv.RequireBindable(context.Background(), f.caller, platform.ID); err != nil || len(f.graph.checked) != 0 {
		t.Fatalf("platform: %v %v", err, f.graph.checked)
	}

	own := ownRow()
	f = newEgressFixture(t, own)
	if err := f.sv.RequireBindable(context.Background(), f.caller, own.ID); err != nil ||
		!slices.Equal(f.graph.checked, []string{authz.CanRead + " " + own.ID}) {
		t.Fatalf("own: %v %v", err, f.graph.checked)
	}
	f.graph.allow = false
	if err := f.sv.RequireBindable(context.Background(), f.caller, own.ID); !errors.Is(err, authz.ErrDenied) {
		t.Fatalf("own without use: %v", err)
	}
	gone := uuid.NewString()
	var nf *api.EgressExitNotFoundError
	if err := f.sv.RequireBindable(context.Background(), f.caller, gone); !errors.As(err, &nf) || nf.Error() != "Egress exit "+gone+" not found" {
		t.Fatalf("gone: %v", err)
	}
}

func TestNothingBindsAnExitOnADeploymentThatCannotEnforceIt(t *testing.T) {
	f := newFixture(t)
	if err := f.sv.RequireBindable(context.Background(), f.caller, uuid.NewString()); !errors.Is(err, api.ErrEgressExitsUnsupported) {
		t.Fatalf("err = %v", err)
	}
	if _, err := f.sv.ListEgressExits(context.Background(), f.caller); !errors.Is(err, api.ErrEgressExitsUnsupported) {
		t.Fatalf("list: %v", err)
	}
}
