package store

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

func TestWorkspacesForUserAndLogo(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	owner := "owner-" + uuid.NewString()
	own := newWorkspace(t, pool, owner)
	joined := newWorkspace(t, pool, "someone-"+uuid.NewString())
	newWorkspace(t, pool, "stranger-"+uuid.NewString())
	got, err := st.ListWorkspacesForUser(ctx, pool, owner, []string{joined.Workspace().ID()})
	if err != nil || len(got) != 2 || got[0].ID != own.Workspace().ID() || got[1].ID != joined.Workspace().ID() {
		t.Fatalf("listed %+v %v", got, err)
	}
	if got, err := st.ListWorkspacesForUser(ctx, pool, owner, nil); err != nil || len(got) != 1 {
		t.Fatalf("without memberships %+v %v", got, err)
	}
	key := "workspace-logos/x/abc"
	if err := st.SetLogoKey(ctx, pool, own.Workspace().ID(), &key, time.Now()); err != nil {
		t.Fatal(err)
	}
	w, ok, err := st.GetWorkspace(ctx, pool, own.Workspace().ID())
	if err != nil || !ok || w.LogoKey == nil || *w.LogoKey != key || w.OwnerUserID != owner {
		t.Fatalf("after set %+v %v %v", w, ok, err)
	}
	if err := st.SetLogoKey(ctx, pool, own.Workspace().ID(), nil, time.Now()); err != nil {
		t.Fatal(err)
	}
	if w, _, _ := st.GetWorkspace(ctx, pool, own.Workspace().ID()); w.LogoKey != nil {
		t.Fatal("logo not cleared")
	}
	if _, ok, err := st.GetWorkspace(ctx, pool, uuid.NewString()); ok || err != nil {
		t.Fatalf("missing workspace found: %v %v", ok, err)
	}
}

func TestEndMembershipRevokesWhatCouldBringTheUserBack(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	s := newWorkspace(t, pool, "owner")
	other := newWorkspace(t, pool, "owner")
	ws := s.Workspace().ID()
	now := time.Date(2026, 11, 12, 1, 0, 0, 0, time.UTC)
	add := func(email *string) domain.Invitation {
		inv, err := st.InsertInvitation(ctx, s, uuid.New(), email, uuid.NewString(), "owner", now.AddDate(0, 0, 7), now)
		if err != nil {
			t.Fatal(err)
		}
		return inv
	}
	str := func(v string) *string { return &v }
	joinedThrough := add(str("Old@Example.com"))
	if err := st.MarkAccepted(ctx, pool, uuid.MustParse(joinedThrough.ID), "member", now, now); err != nil {
		t.Fatal(err)
	}
	if _, err := st.AddForInvitation(ctx, pool, uuid.MustParse(joinedThrough.ID), ws, "member", now, now); err != nil {
		t.Fatal(err)
	}
	toOldAddress := add(str(" old@example.COM "))
	toDirectoryAddress := add(str("new@example.com"))
	toSomeoneElse := add(str("else@example.com"))
	open := add(nil)
	elsewhere, err := st.InsertInvitation(ctx, other, uuid.New(), str("new@example.com"), uuid.NewString(), "owner", now.AddDate(0, 0, 7), now)
	if err != nil {
		t.Fatal(err)
	}
	keyOf := func(by string) uuid.UUID {
		id := uuid.New()
		if _, err := st.InsertAPIKey(ctx, s, NewAPIKey{ID: id, CreatedBy: by, Name: by, TokenHash: uuid.NewString(), TokenPrefix: "aat_x"}, now); err != nil {
			t.Fatal(err)
		}
		return id
	}
	memberKey, ownerKey := keyOf("member"), keyOf("owner")
	fold := func(e string) string { return strings.ToLower(strings.TrimSpace(e)) }
	if err := st.EndMembership(ctx, s, "member", []string{"new@example.com"}, fold, now); err != nil {
		t.Fatal(err)
	}
	if ok, _ := st.MembershipExists(ctx, pool, ws, "member"); ok {
		t.Fatal("membership row survived")
	}
	status := func(id string) string {
		inv, _, err := st.InvitationByID(ctx, pool, uuid.MustParse(id))
		if err != nil {
			t.Fatal(err)
		}
		return inv.Status
	}
	for id, want := range map[string]string{
		joinedThrough.ID: domain.StatusRevoked, toOldAddress.ID: domain.StatusRevoked, toDirectoryAddress.ID: domain.StatusRevoked,
		toSomeoneElse.ID: domain.StatusPending, open.ID: domain.StatusPending, elsewhere.ID: domain.StatusPending,
	} {
		if got := status(id); got != want {
			t.Errorf("invitation %s: %s, want %s", id, got, want)
		}
	}
	for id, want := range map[uuid.UUID]bool{memberKey: false, ownerKey: true} {
		k, _, err := st.APIKeyByID(ctx, s, id)
		if err != nil || k.IsActive != want {
			t.Errorf("key %s active %v, want %v (%v)", id, k.IsActive, want, err)
		}
	}
	pending, err := st.ListPendingInvitations(ctx, s)
	if err != nil || len(pending) != 2 {
		t.Fatalf("pending %+v %v", pending, err)
	}
}

func TestInvitationRevokeIsScopedToTheWorkspace(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	s := newWorkspace(t, pool, "owner")
	other := newWorkspace(t, pool, "owner")
	now := time.Date(2026, 11, 12, 1, 0, 0, 0, time.UTC)
	inv, err := st.InsertInvitation(ctx, s, uuid.New(), nil, uuid.NewString(), "owner", now.AddDate(0, 0, 7), now)
	if err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(inv.ID)
	if err := st.RevokeInvitation(ctx, other, id, now); err != nil {
		t.Fatal(err)
	}
	if got, _, _ := st.InvitationByID(ctx, pool, id); got.Status != domain.StatusPending {
		t.Fatal("another workspace revoked the invitation")
	}
	if err := st.RevokeInvitation(ctx, s, id, now); err != nil {
		t.Fatal(err)
	}
	if got, _, _ := st.InvitationByID(ctx, pool, id); got.Status != domain.StatusRevoked {
		t.Fatal("not revoked")
	}
}

func TestAPIKeysListFiltersAndScope(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	s := newWorkspace(t, pool, "owner")
	other := newWorkspace(t, pool, "owner")
	base := time.Date(2026, 11, 12, 1, 0, 0, 0, time.UTC)
	agent := uuid.New()
	ins := func(by string, agentID *uuid.UUID, at time.Time) uuid.UUID {
		id := uuid.New()
		if _, err := st.InsertAPIKey(ctx, s, NewAPIKey{ID: id, CreatedBy: by, Name: by, TokenHash: uuid.NewString(), TokenPrefix: "aat_x", AgentID: agentID}, at); err != nil {
			t.Fatal(err)
		}
		return id
	}
	a := ins("alice", nil, base)
	b := ins("bob", &agent, base.Add(time.Minute))
	c := ins("alice", &agent, base.Add(2*time.Minute))
	all, err := st.ListAPIKeys(ctx, s, nil, nil)
	if err != nil || len(all) != 3 || all[0].ID != c.String() || all[2].ID != a.String() {
		t.Fatalf("all %+v %v", all, err)
	}
	alice := "alice"
	mine, _ := st.ListAPIKeys(ctx, s, &alice, nil)
	if len(mine) != 2 {
		t.Fatalf("alice's %+v", mine)
	}
	bound, _ := st.ListAPIKeys(ctx, s, nil, &agent)
	if len(bound) != 2 || bound[1].ID != b.String() {
		t.Fatalf("agent's %+v", bound)
	}
	both, _ := st.ListAPIKeys(ctx, s, &alice, &agent)
	if len(both) != 1 || both[0].ID != c.String() || both[0].CreatedBy != "alice" {
		t.Fatalf("alice's agent key %+v", both)
	}
	if _, ok, _ := st.APIKeyByID(ctx, other, a); ok {
		t.Fatal("another workspace read the key")
	}
	if err := st.DeactivateAPIKey(ctx, other, a, base); err != nil {
		t.Fatal(err)
	}
	if k, _, _ := st.APIKeyByID(ctx, s, a); !k.IsActive {
		t.Fatal("another workspace revoked the key")
	}
	if err := st.DeactivateAPIKey(ctx, s, a, base); err != nil {
		t.Fatal(err)
	}
	if k, _, _ := st.APIKeyByID(ctx, s, a); k.IsActive {
		t.Fatal("key still active")
	}
}

func TestMembershipsListedOldestFirst(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	s := newWorkspace(t, pool, "owner")
	ws := s.Workspace().ID()
	base := time.Date(2026, 11, 12, 1, 0, 0, 0, time.UTC)
	for i, u := range []string{"b", "a"} {
		if err := st.AddMembership(ctx, pool, ws, u, base.Add(time.Duration(i)*time.Minute)); err != nil {
			t.Fatal(err)
		}
	}
	rows, err := st.ListMemberships(ctx, pool, ws)
	if err != nil || len(rows) != 2 || rows[0].UserID != "b" || rows[0].InvitationID != nil || !rows[0].CreatedAt.Equal(base) {
		t.Fatalf("rows %+v %v", rows, err)
	}
	ids, err := st.MembershipUserIDs(ctx, pool, ws)
	if err != nil || len(ids) != 2 {
		t.Fatalf("ids %v %v", ids, err)
	}
}

func TestExternalIdentitiesLiveOnly(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	user := "u-" + uuid.NewString()
	now := time.Date(2026, 11, 12, 1, 0, 0, 0, time.UTC)
	first, err := st.InsertExternalIdentity(ctx, pool, user, "telegram", "1"+uuid.NewString()[:8], "deep_link", now)
	if err != nil {
		t.Fatal(err)
	}
	second, err := st.InsertExternalIdentity(ctx, pool, user, "telegram", "2"+uuid.NewString()[:8], "deep_link", now.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if ok, err := st.RevokeExternalIdentity(ctx, pool, "someone-else", uuid.MustParse(first.ID), now); ok || err != nil {
		t.Fatalf("someone else unlinked it: %v %v", ok, err)
	}
	if ok, err := st.RevokeExternalIdentity(ctx, pool, user, uuid.MustParse(first.ID), now); !ok || err != nil {
		t.Fatalf("unlink %v %v", ok, err)
	}
	if ok, _ := st.RevokeExternalIdentity(ctx, pool, user, uuid.MustParse(first.ID), now); ok {
		t.Fatal("unlinked twice")
	}
	live, err := st.ListExternalIdentities(ctx, pool, user)
	if err != nil || len(live) != 1 || live[0].ID != second.ID {
		t.Fatalf("live %+v %v", live, err)
	}
	holder, ok, err := st.ExternalIdentityHolder(ctx, pool, "telegram", second.ExternalID)
	if err != nil || !ok || holder != user {
		t.Fatalf("holder %q %v %v", holder, ok, err)
	}
	ids, err := st.LinkedExternalIDs(ctx, pool, user, "telegram")
	if err != nil || len(ids) != 1 || ids[0] != second.ExternalID {
		t.Fatalf("linked ids %v %v", ids, err)
	}
	if ids, err := st.LinkedExternalIDs(ctx, pool, user, "slack"); err != nil || len(ids) != 0 {
		t.Fatalf("another provider's ids %v %v", ids, err)
	}
}
