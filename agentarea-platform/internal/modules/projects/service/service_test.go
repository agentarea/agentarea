package service

import (
	"context"
	"errors"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type row struct {
	ws string
	p  domain.Project
}

type fakeStore struct {
	rows  map[uuid.UUID]row
	links map[string]*domain.Links
}

func newStore() *fakeStore {
	return &fakeStore{rows: map[uuid.UUID]row{}, links: map[string]*domain.Links{}}
}

func (f *fakeStore) Create(_ context.Context, s db.Session, id uuid.UUID, by string, n domain.New, _ time.Time) (domain.Project, error) {
	p := domain.Project{ID: id.String(), WorkspaceID: s.Workspace().ID(), CreatedBy: by, Name: n.Name,
		Description: n.Description, Instructions: n.Instructions, ParentProjectID: n.ParentProjectID}
	f.rows[id] = row{s.Workspace().ID(), p}
	return p, nil
}

func (f *fakeStore) Get(_ context.Context, s db.Session, id uuid.UUID) (domain.Project, bool, error) {
	r, ok := f.rows[id]
	if !ok || r.ws != s.Workspace().ID() {
		return domain.Project{}, false, nil
	}
	return r.p, true, nil
}

func (f *fakeStore) List(_ context.Context, s db.Session, _, _ int32) ([]domain.Project, error) {
	var out []domain.Project
	for _, r := range f.rows {
		if r.ws == s.Workspace().ID() {
			out = append(out, r.p)
		}
	}
	return out, nil
}

func (f *fakeStore) Node(ctx context.Context, s db.Session, id uuid.UUID) (domain.Node, bool, error) {
	p, ok, err := f.Get(ctx, s, id)
	return domain.Node{Name: p.Name, Instructions: p.Instructions, ParentProjectID: p.ParentProjectID}, ok, err
}

func (f *fakeStore) AgentProjects(_ context.Context, s db.Session, agentID uuid.UUID) ([]uuid.UUID, error) {
	var out []uuid.UUID
	for id, l := range f.links {
		if r, ok := f.rows[uuid.MustParse(id)]; ok && r.ws == s.Workspace().ID() && slices.Contains(l.Agents, agentID.String()) {
			out = append(out, uuid.MustParse(id))
		}
	}
	return out, nil
}

func (f *fakeStore) Update(ctx context.Context, s db.Session, id uuid.UUID, p domain.Patch, _ time.Time) (bool, error) {
	cur, ok, _ := f.Get(ctx, s, id)
	if !ok {
		return false, nil
	}
	if p.ParentProjectID.Set {
		cur.ParentProjectID = p.ParentProjectID.Value
	}
	if p.Name != nil {
		cur.Name = *p.Name
	}
	f.rows[id] = row{s.Workspace().ID(), cur}
	return true, nil
}

func (f *fakeStore) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	_, ok, _ := f.Get(ctx, s, id)
	delete(f.rows, id)
	return ok, nil
}

func (f *fakeStore) Links(_ context.Context, _ db.Session, ids []uuid.UUID) (map[string]*domain.Links, error) {
	out := map[string]*domain.Links{}
	for _, id := range ids {
		if l, ok := f.links[id.String()]; ok {
			out[id.String()] = l
		} else {
			out[id.String()] = &domain.Links{}
		}
	}
	return out, nil
}

func (f *fakeStore) Link(_ context.Context, _ db.Session, k domain.LinkKind, project, child uuid.UUID) error {
	l, ok := f.links[project.String()]
	if !ok {
		l = &domain.Links{}
		f.links[project.String()] = l
	}
	switch k {
	case domain.LinkSkill:
		l.Skills = append(l.Skills, child.String())
	case domain.LinkMCPInstance:
		l.MCPInstances = append(l.MCPInstances, child.String())
	case domain.LinkAgent:
		l.Agents = append(l.Agents, child.String())
	}
	return nil
}

func (f *fakeStore) Unlink(context.Context, db.Session, domain.LinkKind, uuid.UUID, uuid.UUID) error {
	return nil
}

// lookups names what the workspace can see.
type lookups struct{ names map[string]string }

func (l lookups) exists(id string) (bool, error) { _, ok := l.names[id]; return ok, nil }

func (l lookups) named(ids []string) (map[string]string, error) {
	out := map[string]string{}
	for _, id := range ids {
		if n, ok := l.names[id]; ok {
			out[id] = n
		}
	}
	return out, nil
}

func (l lookups) AgentIDBySlug(context.Context, scope.Workspace, string) (string, bool, error) {
	return "", false, nil
}

func (l lookups) AgentExists(_ context.Context, _ scope.Workspace, id string) (bool, error) {
	return l.exists(id)
}
func (l lookups) SkillExists(_ context.Context, _ scope.Workspace, id string) (bool, error) {
	return l.exists(id)
}
func (l lookups) MCPInstanceExists(_ context.Context, _ scope.Workspace, id string) (bool, error) {
	return l.exists(id)
}
func (l lookups) AgentNames(_ context.Context, _ scope.Workspace, ids []string) (map[string]string, error) {
	return l.named(ids)
}
func (l lookups) SkillNames(_ context.Context, _ scope.Workspace, ids []string) (map[string]string, error) {
	return l.named(ids)
}
func (l lookups) MCPInstanceNames(_ context.Context, _ scope.Workspace, ids []string) (map[string]string, error) {
	return l.named(ids)
}

func setup(t *testing.T, names map[string]string) (*Service, *fakeStore, scope.Workspace, scope.Workspace) {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	other, err := scope.NewWorkspace(uuid.NewString(), "other")
	if err != nil {
		t.Fatal(err)
	}
	st := newStore()
	l := lookups{names: names}
	return New(Deps{DB: fakeDB{}, Store: st, Agents: l, Connections: l}), st, ws, other
}

func notFound(t *testing.T, err error, label string) {
	t.Helper()
	var nf *domain.NotFoundError
	if !errors.As(err, &nf) || nf.Label != label {
		t.Fatalf("got %v, want %s not found", err, label)
	}
}

func TestCreateRefusesAParentOutsideTheWorkspace(t *testing.T) {
	ctx := context.Background()
	svc, _, ws, other := setup(t, nil)
	foreign, err := svc.Create(ctx, other, "u", domain.New{Name: "F"})
	if err != nil {
		t.Fatal(err)
	}
	_, err = svc.Create(ctx, ws, "u", domain.New{Name: "C", ParentProjectID: &foreign.ID})
	notFound(t, err, "Parent project")
	bad := "not-a-uuid"
	_, err = svc.Create(ctx, ws, "u", domain.New{Name: "C", ParentProjectID: &bad})
	notFound(t, err, "Parent project")
}

func TestUpdateRefusesCycles(t *testing.T) {
	ctx := context.Background()
	svc, _, ws, _ := setup(t, nil)
	root, _ := svc.Create(ctx, ws, "u", domain.New{Name: "R"})
	child, _ := svc.Create(ctx, ws, "u", domain.New{Name: "C", ParentProjectID: &root.ID})
	rootID := uuid.MustParse(root.ID)
	for _, parent := range []string{root.ID, child.ID} {
		_, err := svc.Update(ctx, ws, rootID, domain.Patch{ParentProjectID: domain.Field{Set: true, Value: &parent}})
		if !errors.Is(err, domain.ErrCycle) {
			t.Fatalf("parent %s: got %v", parent, err)
		}
	}
	upper := "  " + child.ID
	_, err := svc.Update(ctx, ws, rootID, domain.Patch{ParentProjectID: domain.Field{Set: true, Value: &upper}})
	notFound(t, err, "Parent project")
	_, err = svc.Update(ctx, ws, uuid.New(), domain.Patch{Name: &root.Name})
	if !errors.Is(err, domain.ErrProjectNotFound) {
		t.Fatalf("missing project: %v", err)
	}
}

func TestLinkChecksProjectThenChildAndListsOnlyVisibleChildren(t *testing.T) {
	ctx := context.Background()
	agent, skill := uuid.NewString(), uuid.NewString()
	svc, st, ws, _ := setup(t, map[string]string{agent: "Helper", skill: "Search"})
	p, _ := svc.Create(ctx, ws, "u", domain.New{Name: "P"})
	id := uuid.MustParse(p.ID)
	notFound(t, svc.Link(ctx, ws, domain.LinkAgent, uuid.New(), agent), "Project")
	notFound(t, svc.Link(ctx, ws, domain.LinkAgent, id, uuid.NewString()), "Agent")
	notFound(t, svc.Link(ctx, ws, domain.LinkMCPInstance, id, "junk"), "MCP instance")
	if err := svc.Link(ctx, ws, domain.LinkAgent, id, agent); err != nil {
		t.Fatal(err)
	}
	if err := svc.Link(ctx, ws, domain.LinkSkill, id, skill); err != nil {
		t.Fatal(err)
	}
	st.links[p.ID].Agents = append(st.links[p.ID].Agents, uuid.NewString())
	got, err := svc.Get(ctx, ws, id)
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(got.Agents, []domain.Ref{{ID: agent, Name: "Helper"}}) ||
		!slices.Equal(got.Skills, []domain.Ref{{ID: skill, Name: "Search"}}) ||
		got.MCPInstances == nil || len(got.MCPInstances) != 0 {
		t.Fatalf("links %+v", got)
	}
}

func TestDeleteMissingIsNotFound(t *testing.T) {
	svc, _, ws, _ := setup(t, nil)
	if err := svc.Delete(context.Background(), ws, uuid.New()); !errors.Is(err, domain.ErrProjectNotFound) {
		t.Fatalf("got %v", err)
	}
}
