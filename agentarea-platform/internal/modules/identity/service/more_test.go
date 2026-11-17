package service

import (
	"context"
	"errors"
	"io"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

type outbox struct{ queued []events.Envelope }

func (o *outbox) publish(_ context.Context, tx db.Session, _ string, e events.Envelope) error {
	if !tx.InTx() {
		return events.ErrNotInTransaction
	}
	o.queued = append(o.queued, e)
	return nil
}

func (g *graph) Read(_ context.Context, q authz.Query) ([]authz.Tuple, error) {
	if g.readFail != nil {
		return nil, g.readFail
	}
	var out []authz.Tuple
	for _, t := range append(slices.Clone(g.tuples), g.writes...) {
		if q.Matches(t) && !slices.Contains(g.deletes, t) {
			out = append(out, t)
		}
	}
	return out, nil
}

func (g *graph) Check(context.Context, string, string, string, string) (bool, error) {
	return g.allowed, g.checkFail
}

func (f *fakeStore) GetWorkspace(_ context.Context, _ db.Querier, id string) (domain.Workspace, bool, error) {
	w, ok := f.workspaces[id]
	return w, ok, nil
}

func (f *fakeStore) ListWorkspacesForUser(_ context.Context, _ db.Querier, user string, member []string) ([]domain.Workspace, error) {
	var out []domain.Workspace
	for _, w := range f.workspaces {
		if w.OwnerUserID == user || slices.Contains(member, w.ID) {
			out = append(out, w)
		}
	}
	slices.SortFunc(out, func(a, b domain.Workspace) int { return strings.Compare(a.ID, b.ID) })
	return out, nil
}

func (f *fakeStore) SetLogoKey(_ context.Context, _ db.Querier, id string, key *string, _ time.Time) error {
	w := f.workspaces[id]
	w.LogoKey = key
	f.workspaces[id] = w
	return nil
}

func (f *fakeStore) InvitationByID(_ context.Context, _ db.Querier, id uuid.UUID) (domain.Invitation, bool, error) {
	inv, ok := f.byID[id.String()]
	return inv, ok, nil
}

func (f *fakeStore) RevokeInvitation(_ context.Context, _ db.Session, id uuid.UUID, _ time.Time) error {
	f.revoked = append(f.revoked, id)
	return nil
}

func (f *fakeStore) ListMemberships(context.Context, db.Querier, string) ([]domain.MembershipRow, error) {
	return f.rows, nil
}

func (f *fakeStore) MembershipUserIDs(context.Context, db.Querier, string) ([]string, error) {
	var out []string
	for _, r := range f.rows {
		out = append(out, r.UserID)
	}
	return out, nil
}

func (f *fakeStore) AddMembership(_ context.Context, _ db.Querier, ws, user string, at time.Time) error {
	f.members[ws+"/"+user] = true
	f.rows = append(f.rows, domain.MembershipRow{UserID: user, CreatedAt: at})
	return nil
}

func (f *fakeStore) EndMembership(_ context.Context, s db.Session, user string, emails []string, _ func(string) string, _ time.Time) error {
	delete(f.members, s.Workspace().ID()+"/"+user)
	f.ended = append(f.ended, user+":"+strings.Join(emails, ","))
	return nil
}

func (f *fakeStore) APIKeyByID(_ context.Context, _ db.Session, id uuid.UUID) (domain.APIKey, bool, error) {
	for _, k := range f.apiKeys {
		if k.ID == id.String() {
			return k, true, nil
		}
	}
	return domain.APIKey{}, false, nil
}

func (f *fakeStore) ListAPIKeys(_ context.Context, _ db.Session, by *string, _ *uuid.UUID) ([]domain.APIKey, error) {
	var out []domain.APIKey
	for _, k := range f.apiKeys {
		if by == nil || k.CreatedBy == *by {
			out = append(out, k)
		}
	}
	return out, nil
}

func (f *fakeStore) DeactivateAPIKey(_ context.Context, _ db.Session, id uuid.UUID, _ time.Time) error {
	f.deactivated = append(f.deactivated, id)
	return nil
}

func caller(t *testing.T, user, wsID string, admin ...string) authn.Caller {
	t.Helper()
	ws, err := scope.NewWorkspace(wsID, "acme")
	if err != nil {
		t.Fatal(err)
	}
	if admin == nil {
		admin = []string{}
	}
	return authn.Caller{Principal: authn.Principal{UserID: user, AdminWorkspaces: admin, Credential: &authn.Credential{Kind: authn.KindSession}}, Workspace: ws}
}

func members(g *graph, ws string, users ...string) {
	for _, u := range users {
		g.tuples = append(g.tuples, authz.WorkspaceMembership(ws, u), authz.WorkspaceBaselineRole(ws, u))
	}
}

func refusalOf(err error) *domain.Refusal {
	var r *domain.Refusal
	errors.As(err, &r)
	return r
}

func TestRemoveMemberAuthority(t *testing.T) {
	ws := uuid.NewString()
	cases := []struct {
		name, actor, target string
		graph               []string
		want                *domain.Refusal
	}{
		{"owner is never removed", "owner", "owner", []string{"owner", "a"}, domain.ErrOwnerRemoval},
		{"owner is never removed by themself either", "a", "owner", []string{"owner", "a"}, domain.ErrOwnerRemoval},
		{"a member cannot remove another", "a", "b", []string{"owner", "a", "b"}, domain.ErrRemovalOwner},
		{"an unknown member", "owner", "ghost", []string{"owner", "a"}, domain.ErrMemberGone},
		{"the last member", "owner", "a", []string{"a"}, domain.ErrLastMember},
	}
	for _, c := range cases {
		svc, st, g := setup("")
		st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
		members(g, ws, c.graph...)
		_, err := svc.RemoveMember(context.Background(), caller(t, c.actor, ws), c.target)
		if refusalOf(err) != c.want {
			t.Errorf("%s: got %v, want %v", c.name, err, c.want)
		}
		if len(st.ended) != 0 {
			t.Errorf("%s: a refused removal ended a membership", c.name)
		}
	}
}

// A run calls as its starter's user id; Python let a run started by the owner
// remove anyone (workspaces/service.py remove).
func TestAnAgentChangesNoMembership(t *testing.T) {
	ws := uuid.NewString()
	for _, c := range []struct{ starter, target string }{{"owner", "a"}, {"a", "a"}} {
		svc, st, g := setup("")
		st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
		members(g, ws, "owner", "a")
		svc.d.Directory = directory{"a": {UserID: "a", Email: ptr("a@x.co")}}
		run := caller(t, c.starter, ws, ws)
		run.Subject = &authn.Subject{Kind: authn.SubjectAgent, ID: "agent-1"}
		if _, err := svc.RemoveMember(context.Background(), run, c.target); refusalOf(err) != domain.ErrAgentMembership {
			t.Errorf("%s's run removed %s: %v", c.starter, c.target, err)
		}
		if _, err := (Toolsets{S: svc}).Invite(context.Background(), run, nil, nil); err == nil {
			t.Errorf("%s's run invited", c.starter)
		}
		if err := (Toolsets{S: svc}).RevokeInvitation(context.Background(), run, uuid.NewString()); err == nil {
			t.Errorf("%s's run revoked an invitation", c.starter)
		}
		if len(st.ended) != 0 {
			t.Errorf("%s's run ended a membership", c.starter)
		}
		if revoked, err := svc.RemoveMember(context.Background(), caller(t, c.starter, ws, ws), c.target); err != nil || !revoked {
			t.Errorf("%s removing %s in person: %v %v", c.starter, c.target, revoked, err)
		}
	}
}

func TestRemoveMemberEndsQueuesAndRevokes(t *testing.T) {
	ws := uuid.NewString()
	svc, st, g := setup("")
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
	members(g, ws, "owner", "a")
	svc.d.Directory = directory{"a": {UserID: "a", Email: ptr("a@x.co")}}
	out := &outbox{}
	svc.d.Outbox = out.publish
	revoked, err := svc.RemoveMember(context.Background(), caller(t, "owner", ws), "a")
	if err != nil || !revoked {
		t.Fatalf("revoked %v %v", revoked, err)
	}
	if len(st.ended) != 1 || st.ended[0] != "a:a@x.co" {
		t.Fatalf("ended %v", st.ended)
	}
	if len(out.queued) != 1 || out.queued[0].EventType != MembershipEndedEvent || out.queued[0].Data["aggregate_type"] != MembershipAggregate || out.queued[0].Data["user_id"] != "a" {
		t.Fatalf("outbox %+v", out.queued)
	}
	if !slices.Contains(g.deletes, authz.WorkspaceMembership(ws, "a")) || !slices.Contains(g.deletes, authz.WorkspaceBaselineRole(ws, "a")) {
		t.Fatalf("graph deletes %v", g.deletes)
	}
}

func TestSelfLeaveWithTheGraphDownIsPending(t *testing.T) {
	ws := uuid.NewString()
	svc, st, g := setup("")
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
	members(g, ws, "owner", "a")
	svc.d.Directory = directory{}
	g.fail = &authz.UnavailableError{Op: "write", Err: errors.New("down")}
	revoked, err := svc.RemoveMember(context.Background(), caller(t, "a", ws), "a")
	if err != nil || revoked {
		t.Fatalf("revoked %v %v", revoked, err)
	}
	if len(st.ended) != 1 {
		t.Fatal("membership not ended")
	}
}

func TestFinishRemovalSparesReadmittedAndOwner(t *testing.T) {
	ws := uuid.NewString()
	svc, st, g := setup("")
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
	st.members[ws+"/back"] = true
	for _, u := range []string{"back", "owner"} {
		if err := svc.FinishRemoval(context.Background(), ws, u); err != nil {
			t.Fatal(err)
		}
	}
	if len(g.deletes) != 0 {
		t.Fatalf("revoked %v", g.deletes)
	}
}

func TestListMembersJoinsRowsAndIdentities(t *testing.T) {
	ws := uuid.NewString()
	svc, st, g := setup("")
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
	members(g, ws, "owner", "legacy", "11111111-1111-1111-1111-111111111111")
	st.rows = []domain.MembershipRow{{UserID: "11111111-1111-1111-1111-111111111111", CreatedAt: now()}}
	svc.d.Directory = directory{"owner": {UserID: "owner", Email: ptr("o@x.co"), DisplayName: ptr("Olga")}}
	c := caller(t, "legacy", ws)
	c.Email = "me@x.co"
	got, err := svc.ListMembers(context.Background(), c)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 || got[0].UserID != "11111111-1111-1111-1111-111111111111" || got[0].ID != got[0].UserID || got[0].JoinedAt == nil {
		t.Fatalf("first %+v", got)
	}
	if got[1].UserID != "legacy" || *got[1].Email != "me@x.co" || *got[1].DisplayName != "me@x.co" || got[1].ID == "legacy" {
		t.Fatalf("caller falls back to their own email: %+v", got[1])
	}
	if got[2].UserID != "owner" || !got[2].IsOwner || *got[2].DisplayName != "Olga" {
		t.Fatalf("owner %+v", got[2])
	}
	g.readFail = &authz.ResponseError{Op: "read", Status: 500}
	if _, err := svc.ListMembers(context.Background(), c); !errors.Is(err, domain.ErrMembershipGraphDown) {
		t.Fatalf("graph down: %v", err)
	}
}

func TestListMembersRecordsThePersonalOwner(t *testing.T) {
	svc, st, g := setup("")
	user := uuid.NewString()
	if _, err := svc.ListMembers(context.Background(), caller(t, user, user)); err != nil {
		t.Fatal(err)
	}
	if !st.members[user+"/"+user] || !slices.Contains(g.writes, authz.WorkspaceMembership(user, user)) {
		t.Fatal("the personal workspace's owner was not recorded")
	}
}

type directory map[string]domain.Identity

func (d directory) Resolve(_ context.Context, ids []string) (map[string]domain.Identity, error) {
	out := map[string]domain.Identity{}
	for _, id := range ids {
		if rec, ok := d[id]; ok {
			out[id] = rec
		}
	}
	return out, nil
}

func (d directory) Lookup(_ context.Context, id string) (*domain.Identity, error) {
	if rec, ok := d[id]; ok {
		return &rec, nil
	}
	return nil, nil
}

func TestInvitationAdminActions(t *testing.T) {
	ws := uuid.NewString()
	svc, st, _ := setup("")
	inv := domain.Invitation{ID: uuid.NewString(), WorkspaceID: ws, Status: domain.StatusPending}
	foreign := domain.Invitation{ID: uuid.NewString(), WorkspaceID: uuid.NewString(), Status: domain.StatusPending}
	accepted := domain.Invitation{ID: uuid.NewString(), WorkspaceID: ws, Status: domain.StatusAccepted}
	for _, i := range []domain.Invitation{inv, foreign, accepted} {
		st.byID[i.ID] = i
	}
	member := caller(t, "member", ws)
	if _, err := svc.RevokeInvitation(context.Background(), member, uuid.MustParse(inv.ID)); !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		t.Fatalf("member revoked: %v", err)
	}
	if _, err := svc.ListInvitations(context.Background(), member); !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		t.Fatalf("member listed: %v", err)
	}
	admin := caller(t, "owner", ws, ws)
	if _, err := svc.RevokeInvitation(context.Background(), admin, uuid.MustParse(foreign.ID)); refusalOf(err) != domain.ErrInvitationIDNotFound {
		t.Fatalf("foreign invitation: %v", err)
	}
	got, err := svc.RevokeInvitation(context.Background(), admin, uuid.MustParse(accepted.ID))
	if err != nil || got.Status != domain.StatusAccepted || len(st.revoked) != 0 {
		t.Fatalf("accepted %+v %v %v", got, err, st.revoked)
	}
	got, err = svc.RevokeInvitation(context.Background(), admin, uuid.MustParse(inv.ID))
	if err != nil || got.Status != domain.StatusRevoked || len(st.revoked) != 1 {
		t.Fatalf("pending %+v %v", got, err)
	}
	agent := admin
	agent.Subject = &authn.Subject{Kind: authn.SubjectAgent, ID: "a"}
	if _, err := svc.RevokeInvitation(context.Background(), agent, uuid.MustParse(inv.ID)); !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		t.Fatalf("a run administered: %v", err)
	}
}

func TestAPIKeyVisibilityAndRevocation(t *testing.T) {
	ws := uuid.NewString()
	svc, st, _ := setup("")
	client := uuid.NewString()
	mine := domain.APIKey{ID: uuid.NewString(), CreatedBy: "me"}
	theirs := domain.APIKey{ID: uuid.NewString(), CreatedBy: "them"}
	runner := domain.APIKey{ID: uuid.NewString(), CreatedBy: "me", ClientID: &client}
	st.apiKeys = []domain.APIKey{mine, theirs, runner}
	c := caller(t, "me", ws)
	ctx := context.Background()
	listed, _ := svc.ListAPIKeys(ctx, c, false, nil)
	if len(listed) != 1 || listed[0].ID != mine.ID {
		t.Fatalf("member listed %+v", listed)
	}
	listed, _ = svc.ListAPIKeys(ctx, c, true, nil)
	if len(listed) != 2 {
		t.Fatalf("admin listed %+v", listed)
	}
	notAdmin := func() (bool, error) { return false, nil }
	if _, err := svc.GetAPIKey(ctx, c, notAdmin, uuid.MustParse(theirs.ID)); refusalOf(err) != domain.ErrAPIKeyNotFound {
		t.Fatalf("member read a colleague's key: %v", err)
	}
	if _, err := svc.GetAPIKey(ctx, c, func() (bool, error) { return true, nil }, uuid.MustParse(runner.ID)); refusalOf(err) != domain.ErrAPIKeyNotFound {
		t.Fatalf("runner key read: %v", err)
	}
	if k, err := svc.GetAPIKey(ctx, c, notAdmin, uuid.MustParse(mine.ID)); err != nil || k.ID != mine.ID {
		t.Fatalf("own key %v", err)
	}
	refuse := func() error { return authz.ErrNotWorkspaceAdmin }
	if err := svc.RevokeAPIKey(ctx, c, refuse, uuid.MustParse(theirs.ID)); !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		t.Fatalf("member revoked a colleague's key: %v", err)
	}
	if err := svc.RevokeAPIKey(ctx, c, refuse, uuid.MustParse(runner.ID)); refusalOf(err) != domain.ErrAPIKeyNotFound {
		t.Fatalf("runner key revoked: %v", err)
	}
	if err := svc.RevokeAPIKey(ctx, c, refuse, uuid.MustParse(mine.ID)); err != nil || len(st.deactivated) != 1 {
		t.Fatalf("own key: %v %v", err, st.deactivated)
	}
	if err := svc.RevokeAPIKey(ctx, c, func() error { return nil }, uuid.MustParse(theirs.ID)); err != nil || len(st.deactivated) != 2 {
		t.Fatalf("admin: %v", err)
	}
}

func TestListWorkspacesProvisionsOnlyForASignedInUser(t *testing.T) {
	svc, st, g := setup("")
	user := uuid.NewString()
	shared := uuid.NewString()
	other := uuid.NewString()
	st.workspaces[shared] = domain.Workspace{ID: shared, Slug: "shared", OwnerUserID: "x"}
	st.workspaces[other] = domain.Workspace{ID: other, Slug: "other", OwnerUserID: "x"}
	members(g, shared, user)
	members(g, other, user)
	key := authn.Principal{UserID: user, Email: "jane@x.co", Credential: &authn.Credential{Kind: authn.KindAPIKey}, AccessibleWorkspaces: []string{shared}, AdminWorkspaces: []string{}}
	got, err := svc.ListWorkspaces(context.Background(), key)
	if err != nil || len(got) != 1 || got[0].ID != shared || got[0].CanAdminister {
		t.Fatalf("api key sees %+v %v", got, err)
	}
	if _, ok := st.workspaces[user]; ok {
		t.Fatal("an API key provisioned a personal workspace")
	}
	session := key
	session.Credential = &authn.Credential{Kind: authn.KindSession}
	got, err = svc.ListWorkspaces(context.Background(), session)
	if err != nil || len(got) != 3 {
		t.Fatalf("session sees %+v %v", got, err)
	}
	personal := st.workspaces[user]
	if personal.Slug != "jane" || personal.Name != "Personal" || personal.OwnerUserID != user {
		t.Fatalf("personal %+v", personal)
	}
	for _, w := range got {
		if w.CanAdminister != (w.ID == user) {
			t.Fatalf("can_administer %+v", w)
		}
	}
}

func TestListWorkspacesWithoutAnEmailStillLists(t *testing.T) {
	svc, st, g := setup("")
	user := uuid.NewString()
	shared := uuid.NewString()
	st.workspaces[shared] = domain.Workspace{ID: shared, OwnerUserID: "x"}
	members(g, shared, user)
	got, err := svc.ListWorkspaces(context.Background(), authn.Principal{UserID: user, Credential: &authn.Credential{Kind: authn.KindOAuth}, AdminWorkspaces: []string{}})
	if err != nil || len(got) != 1 {
		t.Fatalf("got %+v %v", got, err)
	}
	if _, ok := st.workspaces[user]; ok {
		t.Fatal("a personal workspace was named without an email")
	}
}

type logos struct {
	put     map[string][]byte
	deleted []string
}

func (l *logos) Put(_ context.Context, key string, body io.Reader, _ int64, _ blob.PutOptions) error {
	b, err := io.ReadAll(body)
	l.put[key] = b
	return err
}
func (l *logos) Delete(_ context.Context, key string) error {
	l.deleted = append(l.deleted, key)
	return nil
}
func (*logos) PresignGet(_ context.Context, key string, _ time.Duration) (blob.Presigned, error) {
	return blob.Presigned{URL: "https://s3/" + key}, nil
}

func TestLogo(t *testing.T) {
	ws := uuid.NewString()
	svc, st, _ := setup("")
	l := &logos{put: map[string][]byte{}}
	svc.d.Logos = l
	old := "workspace-logos/" + ws + "/old"
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner", LogoKey: &old}
	admin := caller(t, "owner", ws, ws)
	ctx := context.Background()
	if _, err := svc.SetLogo(ctx, caller(t, "member", ws), []byte("\x89PNG\r\n\x1a\n")); !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		t.Fatalf("member set the logo: %v", err)
	}
	if _, err := svc.SetLogo(ctx, admin, make([]byte, domain.LogoMaxBytes+1)); refusalOf(err) != domain.ErrLogoTooLarge {
		t.Fatalf("too large: %v", err)
	}
	if _, err := svc.SetLogo(ctx, admin, []byte("GIF89a")); refusalOf(err) != domain.ErrLogoType {
		t.Fatalf("gif: %v", err)
	}
	v, err := svc.SetLogo(ctx, admin, []byte("RIFF\x00\x00\x00\x00WEBPVP8 "))
	if err != nil || v.LogoURL == nil || !strings.HasPrefix(*v.LogoURL, "https://s3/workspace-logos/"+ws+"/") || !v.CanAdminister {
		t.Fatalf("set %+v %v", v, err)
	}
	if len(l.deleted) != 1 || l.deleted[0] != old {
		t.Fatalf("deleted %v", l.deleted)
	}
	v, err = svc.RemoveLogo(ctx, admin)
	if err != nil || v.LogoURL != nil || st.workspaces[ws].LogoKey != nil || len(l.deleted) != 2 {
		t.Fatalf("removed %+v %v %v", v, err, l.deleted)
	}
}

type resources struct {
	agents, collections, servers, skills []Named
	counts                               map[string]int
}

func (r resources) Exists(_ context.Context, _ scope.Workspace, ns string, id uuid.UUID) (bool, error) {
	for _, list := range [][]Named{r.agents, r.collections, r.servers, r.skills} {
		for _, n := range list {
			if n.ID == id.String() {
				return true, nil
			}
		}
	}
	return false, nil
}
func (r resources) Agents(context.Context, scope.Workspace, bool) ([]Named, error) {
	return r.agents, nil
}
func (r resources) Collections(context.Context, scope.Workspace) ([]Named, error) {
	return r.collections, nil
}
func (r resources) SkillCounts(context.Context, scope.Workspace) (map[string]int, error) {
	return r.counts, nil
}
func (r resources) MCPServers(context.Context, scope.Workspace) ([]Named, error) {
	return r.servers, nil
}
func (r resources) Skills(context.Context, scope.Workspace) ([]Named, error) { return r.skills, nil }

func TestExplorerRefusals(t *testing.T) {
	ws := uuid.NewString()
	svc, st, _ := setup("")
	agent := uuid.NewString()
	svc.d.Resources = resources{agents: []Named{{ID: agent, Name: "A"}}}
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
	admin := caller(t, "owner", ws, ws)
	ctx := context.Background()
	sub := func(s string) *string { return &s }
	cases := []struct {
		w    RelationshipWrite
		want string
	}{
		{RelationshipWrite{Namespace: "Workspace", Object: agent, Relation: "reader", SubjectID: sub("User:owner")}, "Unsupported namespace: 'Workspace'"},
		{RelationshipWrite{Namespace: "Agent", Object: "it's", Relation: "reader", SubjectID: sub("User:owner")}, `Invalid object id: "it's"`},
		{RelationshipWrite{Namespace: "Agent", Object: uuid.NewString(), Relation: "reader", SubjectID: sub("User:owner")}, "not found in your workspace"},
		{RelationshipWrite{Namespace: "Agent", Object: agent, Relation: "reader", SubjectID: sub("User:stranger")}, "Subject user is not in your workspace"},
		{RelationshipWrite{Namespace: "Agent", Object: agent, Relation: "reader"}, "Unsupported subject: ''"},
		{RelationshipWrite{Namespace: "Agent", Object: agent, Relation: "reader", SubjectID: sub("Team:x")}, "Unsupported subject: 'Team:x'"},
		{RelationshipWrite{Namespace: "Agent", Object: agent, Relation: "admin", SubjectID: sub("User:owner")}, "Unsupported relation for a resource grant: 'admin'"},
	}
	for _, c := range cases {
		err := svc.GrantRelationship(ctx, admin, c.w)
		if r := refusalOf(err); r == nil || !strings.Contains(r.Detail, c.want) {
			t.Errorf("%+v: got %v, want %q", c.w, err, c.want)
		}
	}
	if err := svc.GrantRelationship(ctx, caller(t, "member", ws), cases[0].w); !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		t.Fatalf("member granted: %v", err)
	}
}

type audits struct{ recs []governanceapi.AuditRecord }

func (a *audits) RecordOnce(_ context.Context, _ db.Session, rec governanceapi.AuditRecord) error {
	a.recs = append(a.recs, rec)
	return nil
}

func TestExplorerGrantRevokeAndGraph(t *testing.T) {
	ws := uuid.NewString()
	svc, st, g := setup("")
	agent, other, skill, coll := uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()
	svc.d.Resources = resources{
		agents:      []Named{{ID: agent, Name: "A"}, {ID: other, Name: "B"}},
		collections: []Named{{ID: coll, Name: "C"}},
		skills:      []Named{{ID: skill, Name: "S"}},
		counts:      map[string]int{coll: 4},
	}
	a := &audits{}
	svc.d.Audit = a
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
	admin := caller(t, "owner", ws, ws)
	ctx := context.Background()
	subject := "Agent:" + agent
	grant := RelationshipWrite{Namespace: "SkillCollection", Object: coll, Relation: "viewers", SubjectID: &subject}
	for range 2 {
		if err := svc.GrantRelationship(ctx, admin, grant); err != nil {
			t.Fatal(err)
		}
	}
	want := authz.Tuple{User: subject, Relation: "reader", Object: "resource:" + coll}
	if len(g.writes) != 1 || g.writes[0] != want || len(a.recs) != 1 || a.recs[0].Action != "access.grant" {
		t.Fatalf("writes %v audits %+v", g.writes, a.recs)
	}
	g.tuples = []authz.Tuple{
		{User: subject, Relation: "manager", Object: "resource:" + skill},
		{User: subject, Relation: "manager", Object: "resource:" + agent},
		{User: "User:owner", Relation: "can_read", Object: "resource:" + other},
	}
	graph, err := svc.AccessGraph(ctx, admin)
	if err != nil {
		t.Fatal(err)
	}
	if len(graph.Nodes) != 3 || graph.Nodes[2].Subtitle != "4 skills" || graph.Nodes[1].Color != "#8b5cf6" {
		t.Fatalf("nodes %+v", graph.Nodes)
	}
	if len(graph.Edges) != 1 || graph.Edges[0] != (GraphEdge{From: subject, To: "SkillCollection:" + coll, Relation: "user"}) {
		t.Fatalf("edges %+v", graph.Edges)
	}
	if graph.Stats != (GraphStats{GovernedSkillCount: 1, RuleCount: 2, DirectExceptionCount: 1}) {
		t.Fatalf("stats %+v", graph.Stats)
	}
	rels, err := svc.Relationships(ctx, admin, nil)
	if err != nil || len(rels) != 3 {
		t.Fatalf("relationships %+v %v", rels, err)
	}
	ns := "Skill"
	rels, _ = svc.Relationships(ctx, admin, &ns)
	if len(rels) != 1 || !rels[0].Direct || rels[0].ObjectName != "S" || rels[0].SubjectName != "A" {
		t.Fatalf("skill relationships %+v", rels)
	}
	bad := "Workspace"
	if _, err := svc.Relationships(ctx, admin, &bad); refusalOf(err) == nil {
		t.Fatal("unsupported namespace accepted")
	}
	g.readFail = &authz.UnavailableError{Op: "read", Err: errors.New("down")}
	if rels, err := svc.Relationships(ctx, admin, nil); err != nil || len(rels) != 0 {
		t.Fatalf("graph down %+v %v", rels, err)
	}
	g.readFail = nil
	if err := svc.RevokeRelationship(ctx, admin, grant); err != nil || len(g.deletes) != 1 || len(a.recs) != 2 {
		t.Fatalf("revoke %v %v %+v", err, g.deletes, a.recs)
	}
}

func TestCheckAndResolve(t *testing.T) {
	ws := uuid.NewString()
	svc, st, g := setup("")
	agent, skill := uuid.NewString(), uuid.NewString()
	svc.d.Resources = resources{agents: []Named{{ID: agent, Name: "A"}}, skills: []Named{{ID: skill, Name: "S"}}}
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
	admin := caller(t, "owner", ws, ws)
	ctx := context.Background()
	subject := "Agent:" + agent
	g.allowed = true
	if ok, err := svc.CheckPermission(ctx, admin, "Skill", skill, "fly", subject); ok || err != nil {
		t.Fatalf("unknown verb %v %v", ok, err)
	}
	if ok, err := svc.CheckPermission(ctx, admin, "Skill", skill, "use", subject); !ok || err != nil {
		t.Fatalf("use %v %v", ok, err)
	}
	g.checkFail = &authz.UnavailableError{Op: "check", Err: errors.New("down")}
	if _, err := svc.CheckPermission(ctx, admin, "Skill", skill, "use", subject); refusalOf(err) == nil || refusalOf(err).Status != 503 {
		t.Fatalf("check down: %v", err)
	}
	g.tuples = []authz.Tuple{
		{User: subject, Relation: "reader", Object: "resource:" + skill},
		{User: subject, Relation: "writer", Object: "resource:" + skill},
		{User: "User:owner", Relation: "manager", Object: "resource:" + skill},
	}
	res, err := svc.ResolveAccess(ctx, admin, subject, "skill", skill)
	if err != nil || res.Allowed || res.Verb != "use" || len(res.Paths) != 2 || *res.EffectiveRelation != "editor" || res.Paths[0].Hops[0].Name != "A" {
		t.Fatalf("resolve %+v %v", res, err)
	}
}

func TestSyncWritesMembersAndOwner(t *testing.T) {
	ws := uuid.NewString()
	svc, st, g := setup("")
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
	st.rows = []domain.MembershipRow{{UserID: "b"}, {UserID: "owner"}}
	n, err := svc.SyncMembers(context.Background(), caller(t, "owner", ws, ws))
	if err != nil || n != 2 || len(g.writes) != 2 {
		t.Fatalf("synced %d %v %v", n, err, g.writes)
	}
	if _, err := svc.SyncMembers(context.Background(), caller(t, "b", ws)); !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		t.Fatalf("member synced: %v", err)
	}
}

func TestResolvePrincipals(t *testing.T) {
	ws := uuid.NewString()
	svc, _, _ := setup("")
	agent := uuid.NewString()
	svc.d.Agents = agentNames{agent: "Bot"}
	svc.d.Directory = directory{"u1": {UserID: "u1", Email: ptr("u1@x.co"), DisplayName: ptr("U One")}}
	c := caller(t, "me", ws)
	c.Email = "me@x.co"
	got, err := svc.ResolvePrincipals(context.Background(), c, []string{"system", "", agent, "u1", "ghost", "me", "u1"})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"system:platform", agent + ":agent", "u1:user", "me:user"}
	var have []string
	for _, p := range got {
		have = append(have, p.ID+":"+p.Type)
	}
	if !slices.Equal(have, want) {
		t.Fatalf("got %v, want %v", have, want)
	}
	many := make([]string, 0, 300)
	for range 300 {
		many = append(many, uuid.NewString())
	}
	svc.d.Directory = everyone{}
	got, _ = svc.ResolvePrincipals(context.Background(), c, many)
	if len(got) != MaxPrincipalIDs {
		t.Fatalf("resolved %d", len(got))
	}
}

type everyone struct{}

func (everyone) Resolve(_ context.Context, ids []string) (map[string]domain.Identity, error) {
	out := map[string]domain.Identity{}
	for _, id := range ids {
		out[id] = domain.Identity{UserID: id, Email: ptr(id + "@x.co")}
	}
	return out, nil
}
func (everyone) Lookup(context.Context, string) (*domain.Identity, error) { return nil, nil }

type agentNames map[string]string

func (agentNames) AgentIDBySlug(context.Context, scope.Workspace, string) (string, bool, error) {
	return "", false, nil
}

func (agentNames) AgentExists(context.Context, scope.Workspace, string) (bool, error) {
	return false, nil
}
func (agentNames) SkillExists(context.Context, scope.Workspace, string) (bool, error) {
	return false, nil
}
func (a agentNames) AgentNames(_ context.Context, _ scope.Workspace, ids []string) (map[string]string, error) {
	out := map[string]string{}
	for _, id := range ids {
		if n, ok := a[id]; ok {
			out[id] = n
		}
	}
	return out, nil
}
func (agentNames) SkillNames(context.Context, scope.Workspace, []string) (map[string]string, error) {
	return nil, nil
}

func TestMemberResponseID(t *testing.T) {
	if got := MemberResponseID("ws", "{11111111-1111-1111-1111-111111111111}"); got != "11111111-1111-1111-1111-111111111111" {
		t.Fatalf("braced uuid %s", got)
	}
	if got := uuid.MustParse(MemberResponseID("ws", "kratos-user")); got.Version() != 5 {
		t.Fatalf("not a uuid5: %s", got)
	}
	if _, ok := PyUUID("1111111111111111111111111111111z"); ok {
		t.Fatal("non-hex read as a uuid")
	}
	if MemberResponseID("ws", "kratos-user") == MemberResponseID("ws2", "kratos-user") {
		t.Fatal("the uuid5 does not depend on the workspace")
	}
}

func TestRemovalRefusesWithoutADirectory(t *testing.T) {
	ws := uuid.NewString()
	svc, st, g := setup("")
	st.workspaces[ws] = domain.Workspace{ID: ws, OwnerUserID: "owner"}
	members(g, ws, "owner", "a")
	out := &outbox{}
	svc.d.Outbox = out.publish
	for _, actor := range []string{"owner", "a"} {
		if _, err := svc.RemoveMember(context.Background(), caller(t, actor, ws), "a"); refusalOf(err) != domain.ErrRemovalNeedsDirectory {
			t.Fatalf("%s removed without a directory: %v", actor, err)
		}
	}
	if len(st.ended) != 0 || len(out.queued) != 0 || len(g.deletes) != 0 {
		t.Fatalf("a refused removal changed state: %v %v %v", st.ended, out.queued, g.deletes)
	}
}

func TestCreationsAreAudited(t *testing.T) {
	ws := uuid.NewString()
	agent := uuid.NewString()
	svc, _, _ := setup(agent)
	a := &audits{}
	svc.d.Audit = a
	c := caller(t, "owner", ws, ws)
	ctx := context.Background()
	inv, err := svc.CreateInvitation(ctx, c, ptr("a@b.co"), nil)
	if err != nil {
		t.Fatal(err)
	}
	open, err := svc.CreateInvitation(ctx, c, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	days := 30
	key, err := svc.CreateAPIKey(ctx, c, "ci", &days, nil)
	if err != nil {
		t.Fatal(err)
	}
	plain, err := svc.CreateAPIKey(ctx, c, "plain", nil, &agent)
	if err != nil {
		t.Fatal(err)
	}
	want := []governanceapi.AuditRecord{
		{Action: "member.invite", ResourceType: "invitation", ResourceID: inv.ID, ActorType: "user", ActorID: "owner", Metadata: map[string]any{"resource_name": "a@b.co"}},
		{Action: "member.invite", ResourceType: "invitation", ResourceID: open.ID, ActorType: "user", ActorID: "owner", Metadata: map[string]any{"resource_name": nil}},
		{Action: "api_key.create", ResourceType: "api_key", ResourceID: key.ID, ActorType: "user", ActorID: "owner", Metadata: map[string]any{
			"resource_name": "ci", "token_prefix": key.TokenPrefix, "agent_id": nil, "expires_at": pyIsoformat(*key.ExpiresAt),
		}},
		{Action: "api_key.create", ResourceType: "api_key", ResourceID: plain.ID, ActorType: "user", ActorID: "owner", Metadata: map[string]any{
			"resource_name": "plain", "token_prefix": plain.TokenPrefix, "agent_id": agent, "expires_at": nil,
		}},
	}
	if len(a.recs) != len(want) {
		t.Fatalf("audits %+v", a.recs)
	}
	for i, rec := range a.recs {
		if _, err := uuid.Parse(rec.EventID); err != nil {
			t.Fatalf("event id %q", rec.EventID)
		}
		rec.EventID = ""
		if !reflect.DeepEqual(rec, want[i]) {
			t.Errorf("audit %d: %+v, want %+v", i, rec, want[i])
		}
	}
}

func TestPyIsoformat(t *testing.T) {
	at := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	if got := pyIsoformat(at); got != "2026-01-02T03:04:05" {
		t.Fatal(got)
	}
	if got := pyIsoformat(at.Add(1500 * time.Nanosecond)); got != "2026-01-02T03:04:05.000001" {
		t.Fatal(got)
	}
}
