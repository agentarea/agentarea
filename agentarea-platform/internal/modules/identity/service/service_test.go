package service

import (
	"context"
	"errors"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/store"
)

type fakeGlobal struct{}

func (fakeGlobal) Read(context.Context) (db.Querier, func(), error) { return nil, func() {}, nil }
func (fakeGlobal) Write(ctx context.Context, fn func(context.Context, db.Querier) error) error {
	return fn(ctx, nil)
}

type fakeDB struct{ db.Database }

func (fakeDB) Global() db.Global { return fakeGlobal{} }
func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

type uniqueViolation struct{}

func (uniqueViolation) Error() string    { return "duplicate key" }
func (uniqueViolation) SQLState() string { return "23505" }

type fakeStore struct {
	Store
	slugs       map[string]bool
	raceOnce    bool
	invitations map[string]domain.Invitation
	members     map[string]bool
	keys        []store.NewAPIKey
	workspaces  map[string]domain.Workspace
	byID        map[string]domain.Invitation
	rows        []domain.MembershipRow
	apiKeys     []domain.APIKey
	deactivated []uuid.UUID
	ended       []string
	revoked     []uuid.UUID
}

func (f *fakeStore) SlugTaken(_ context.Context, _ db.Querier, slug string) (bool, error) {
	return f.slugs[slug], nil
}

func (f *fakeStore) InsertWorkspace(_ context.Context, _ db.Querier, w domain.Workspace) (domain.Workspace, error) {
	if f.raceOnce {
		f.raceOnce = false
		f.slugs[w.Slug] = true
		return domain.Workspace{}, uniqueViolation{}
	}
	f.slugs[w.Slug] = true
	if f.workspaces != nil {
		f.workspaces[w.ID] = w
	}
	return w, nil
}

func (f *fakeStore) InvitationByTokenHash(_ context.Context, _ db.Querier, h string) (domain.Invitation, bool, error) {
	inv, ok := f.invitations[h]
	return inv, ok, nil
}

func (f *fakeStore) MarkAccepted(_ context.Context, _ db.Querier, id uuid.UUID, userID string, at, _ time.Time) error {
	for h, inv := range f.invitations {
		if inv.ID == id.String() {
			inv.Status, inv.AcceptedByUserID, inv.AcceptedAt = domain.StatusAccepted, &userID, &at
			f.invitations[h] = inv
		}
	}
	return nil
}

func (f *fakeStore) AddForInvitation(_ context.Context, _ db.Querier, id uuid.UUID, ws, userID string, at, _ time.Time) (bool, error) {
	for h, inv := range f.invitations {
		if inv.ID == id.String() {
			if inv.Status != domain.StatusAccepted || *inv.AcceptedByUserID != userID {
				return false, nil
			}
			f.members[ws+"/"+userID] = true
			inv.MembershipGrantedAt = &at
			f.invitations[h] = inv
			return true, nil
		}
	}
	return false, nil
}

func (f *fakeStore) MembershipExists(_ context.Context, _ db.Querier, ws, userID string) (bool, error) {
	return f.members[ws+"/"+userID], nil
}

func (f *fakeStore) InsertInvitation(_ context.Context, s db.Session, id uuid.UUID, email *string, h, by string, expires, now time.Time) (domain.Invitation, error) {
	inv := domain.Invitation{ID: id.String(), CreatedAt: now, WorkspaceID: s.Workspace().ID(), Email: email, InvitedBy: by, Status: domain.StatusPending, ExpiresAt: expires}
	f.invitations[h] = inv
	return inv, nil
}

func (f *fakeStore) InsertAPIKey(_ context.Context, _ db.Session, k store.NewAPIKey, now time.Time) (domain.APIKey, error) {
	f.keys = append(f.keys, k)
	var agent *string
	if k.AgentID != nil {
		a := k.AgentID.String()
		agent = &a
	}
	return domain.APIKey{ID: k.ID.String(), Name: k.Name, TokenPrefix: k.TokenPrefix, IsActive: true, ExpiresAt: k.ExpiresAt, AgentID: agent, CreatedAt: now}, nil
}

type graph struct {
	writes, deletes []authz.Tuple
	fail            error
	tuples          []authz.Tuple
	readFail        error
	allowed         bool
	checkFail       error
}

func (g *graph) Write(_ context.Context, w, d []authz.Tuple) error {
	if g.fail != nil {
		return g.fail
	}
	for _, t := range w {
		if slices.Contains(g.writes, t) && !slices.Contains(g.deletes, t) {
			return &authz.ResponseError{Op: "write", Status: 400, Body: "tuple to be written already existed"}
		}
	}
	for _, t := range d {
		if !slices.Contains(g.writes, t) && !slices.Contains(g.tuples, t) {
			return &authz.ResponseError{Op: "write", Status: 400, Body: "tuple to be deleted did not exist"}
		}
	}
	g.writes, g.deletes = append(g.writes, w...), append(g.deletes, d...)
	return nil
}

type agents struct{ known string }

func (agents) AgentIDBySlug(context.Context, scope.Workspace, string) (string, bool, error) {
	return "", false, nil
}

func (a agents) AgentExists(_ context.Context, _ scope.Workspace, id string) (bool, error) {
	return id == a.known, nil
}
func (agents) SkillExists(context.Context, scope.Workspace, string) (bool, error) { return false, nil }
func (agents) AgentNames(context.Context, scope.Workspace, []string) (map[string]string, error) {
	return nil, nil
}
func (agents) SkillNames(context.Context, scope.Workspace, []string) (map[string]string, error) {
	return nil, nil
}

func now() time.Time { return time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC) }

func setup(agentID string) (*Service, *fakeStore, *graph) {
	st := &fakeStore{slugs: map[string]bool{}, invitations: map[string]domain.Invitation{}, members: map[string]bool{}}
	st.workspaces, st.byID = map[string]domain.Workspace{}, map[string]domain.Invitation{}
	g := &graph{}
	discard := func(context.Context, db.Session, string, events.Envelope) error { return nil }
	return New(Deps{DB: fakeDB{}, Store: st, Graph: g, Reader: g, Agents: agents{agentID}, Now: now, Outbox: discard}, nil), st, g
}

func TestCreateWorkspaceTakesTheNextFreeSlugAndRetriesARace(t *testing.T) {
	svc, st, g := setup("")
	st.slugs["acme"] = true
	st.raceOnce = true
	w, err := svc.CreateWorkspace(context.Background(), "owner", "Acme")
	if err != nil {
		t.Fatal(err)
	}
	if w.Slug != "acme-3" || w.OwnerUserID != "owner" || w.Name != "Acme" {
		t.Fatalf("workspace %+v", w)
	}
	if len(g.writes) == 0 {
		t.Fatal("the graph was not seeded")
	}
}

func TestCreateWorkspaceGivesUpAfterFiveRaces(t *testing.T) {
	svc, st, _ := setup("")
	var calls int
	svc.d.Store = racing{st, &calls}
	_, err := svc.CreateWorkspace(context.Background(), "owner", "Acme")
	if !errors.Is(err, domain.ErrSlugsExhausted) || calls != insertAttempts {
		t.Fatalf("got %v after %d inserts", err, calls)
	}
}

type racing struct {
	*fakeStore
	calls *int
}

func (r racing) InsertWorkspace(context.Context, db.Querier, domain.Workspace) (domain.Workspace, error) {
	*r.calls++
	return domain.Workspace{}, uniqueViolation{}
}

func invitation(st *fakeStore, token string, email *string, status string, expires time.Time) domain.Invitation {
	inv := domain.Invitation{ID: uuid.NewString(), WorkspaceID: "ws", Email: email, Status: status, ExpiresAt: expires}
	st.invitations[hashToken(token)] = inv
	return inv
}

func ptr(s string) *string { return &s }

func TestAcceptRefusals(t *testing.T) {
	ctx := context.Background()
	member := authn.Principal{UserID: "member", Email: "Member@Example.com "}
	cases := []struct {
		name string
		prep func(st *fakeStore)
		want error
	}{
		{"unknown token", func(*fakeStore) {}, domain.ErrInvitationNotFound},
		{"other address", func(st *fakeStore) {
			invitation(st, "t", ptr("x@example.com"), domain.StatusPending, now().Add(time.Hour))
		}, domain.ErrAddressedElsewhere},
		{"revoked", func(st *fakeStore) { invitation(st, "t", nil, domain.StatusRevoked, now().Add(time.Hour)) }, domain.ErrInvitationRevoked},
		{"accepted by another", func(st *fakeStore) {
			inv := invitation(st, "t", nil, domain.StatusAccepted, now().Add(time.Hour))
			inv.AcceptedByUserID = ptr("someone")
			st.invitations[hashToken("t")] = inv
		}, domain.ErrInvitationAccepted},
		{"expired", func(st *fakeStore) { invitation(st, "t", nil, domain.StatusPending, now()) }, domain.ErrInvitationExpired},
	}
	for _, c := range cases {
		svc, st, _ := setup("")
		c.prep(st)
		if _, err := svc.AcceptInvitation(ctx, member, "t"); !errors.Is(err, c.want) {
			t.Errorf("%s: got %v, want %v", c.name, err, c.want)
		}
	}
}

func TestAcceptGrantsOnceAndCaseFoldsTheAddress(t *testing.T) {
	ctx := context.Background()
	svc, st, g := setup("")
	invitation(st, "t", ptr(" member@EXAMPLE.com"), domain.StatusPending, now().Add(time.Hour))
	p := authn.Principal{UserID: "member", Email: "Member@example.com"}
	inv, err := svc.AcceptInvitation(ctx, p, "t")
	if err != nil {
		t.Fatal(err)
	}
	if inv.Status != domain.StatusAccepted || !st.members["ws/member"] || len(g.writes) != 2 {
		t.Fatalf("inv %+v members %v writes %v", inv, st.members, g.writes)
	}
	if _, err := svc.AcceptInvitation(ctx, p, "t"); err != nil {
		t.Fatalf("re-accepting by the same user: %v", err)
	}
	if len(g.writes) != 2 {
		t.Fatalf("a granted invitation wrote the graph again: %v", g.writes)
	}
}

func TestAcceptWithTheGraphDownIs503(t *testing.T) {
	svc, st, g := setup("")
	invitation(st, "t", nil, domain.StatusPending, now().Add(time.Hour))
	g.fail = &authz.UnavailableError{Op: "write", Err: errors.New("refused")}
	_, err := svc.AcceptInvitation(context.Background(), authn.Principal{UserID: "member"}, "t")
	if !errors.Is(err, domain.ErrMembershipGraphDown) {
		t.Fatalf("got %v", err)
	}
}

func TestCreateInvitation(t *testing.T) {
	svc, _, _ := setup("")
	ws, _ := scope.NewWorkspace(uuid.NewString(), "acme")
	c := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	got, err := svc.CreateInvitation(context.Background(), c, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if got.EmailDelivery != domain.DeliveryNotRequested || len(got.Token) != 43 {
		t.Fatalf("invitation %+v", got)
	}
	got, err = svc.CreateInvitation(context.Background(), c, ptr("a@b.co"), nil)
	if err != nil || got.EmailDelivery != domain.DeliveryNotConfigured {
		t.Fatalf("addressed invitation %+v %v", got, err)
	}
}

func TestCreateAPIKey(t *testing.T) {
	agent := uuid.NewString()
	svc, st, _ := setup(agent)
	ws, _ := scope.NewWorkspace(uuid.NewString(), "acme")
	c := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	if _, err := svc.CreateAPIKey(context.Background(), c, "k", nil, ptr(uuid.NewString())); !errors.Is(err, domain.ErrAgentNotFound) {
		t.Fatalf("unknown agent: %v", err)
	}
	days := 30
	k, err := svc.CreateAPIKey(context.Background(), c, "k", &days, &agent)
	if err != nil {
		t.Fatal(err)
	}
	if k.Token[:12] != k.TokenPrefix || st.keys[0].AgentID.String() != agent || st.keys[0].CreatedBy != "owner" ||
		!k.ExpiresAt.Equal(now().AddDate(0, 0, 30)) {
		t.Fatalf("key %+v stored %+v", k, st.keys[0])
	}
}
