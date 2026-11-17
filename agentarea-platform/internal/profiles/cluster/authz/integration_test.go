package authz

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"strconv"
	"testing"
	"time"

	kauthz "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
)

// openGraph bootstraps a fresh store with the packaged model on
// AGENTAREA_TEST_OPENFGA_URL and skips when it is unset.
func openGraph(t *testing.T) (*Client, kauthz.Config) {
	t.Helper()
	url := os.Getenv("AGENTAREA_TEST_OPENFGA_URL")
	if url == "" {
		t.Skip("AGENTAREA_TEST_OPENFGA_URL is not set")
	}
	cfg := kauthz.Config{
		Backend:    "openfga",
		URL:        url,
		Timeout:    10 * time.Second,
		Bootstrap:  true,
		ApplyModel: true,
		StoreName:  "aa-go-authz-" + strconv.FormatInt(time.Now().UnixNano(), 36),
	}
	c, settled, err := Open(context.Background(), cfg, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if settled.StoreID == "" || settled.ModelID == "" {
		t.Fatalf("bootstrap settled on %+v", settled)
	}
	return c, cfg
}

type expect struct {
	subject, relation, object string
	want                      bool
}

func assertChecks(t *testing.T, c *Client, cases []expect) {
	t.Helper()
	ctx := context.Background()
	items := make([]kauthz.CheckItem, len(cases))
	for i, e := range cases {
		typ, id := kauthz.SplitObject(e.object)
		items[i] = kauthz.CheckItem{Subject: e.subject, Relation: e.relation, ObjectType: typ, ObjectID: id}
		got, err := c.Check(ctx, e.subject, e.relation, typ, id)
		if err != nil {
			t.Fatalf("check %v: %v", e, err)
		}
		if got != e.want {
			t.Errorf("%s %s %s = %v, want %v", e.subject, e.relation, e.object, got, e.want)
		}
	}
	batch, err := c.BatchCheck(ctx, items)
	if err != nil {
		t.Fatal(err)
	}
	for i, e := range cases {
		if batch[i] != e.want {
			t.Errorf("batch %s %s %s = %v, want %v", e.subject, e.relation, e.object, batch[i], e.want)
		}
	}
}

func TestBootstrapConverges(t *testing.T) {
	c, cfg := openGraph(t)
	again, settled, err := Open(context.Background(), cfg, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if again.StoreID() != c.StoreID() || settled.ModelID != c.ModelID() {
		t.Fatalf("second bootstrap: store %s model %s, first %s %s", again.StoreID(), settled.ModelID, c.StoreID(), c.ModelID())
	}
	pinned := cfg
	pinned.StoreID = c.StoreID()
	pinned.Bootstrap = false
	if _, _, err := Open(context.Background(), pinned, Options{}); err != nil {
		t.Fatal(err)
	}
	pinned.StoreID = ""
	if _, _, err := Open(context.Background(), pinned, Options{}); err == nil {
		t.Fatal("no store id and no bootstrap accepted")
	}
}

func TestWorkspaceMembers(t *testing.T) {
	ctx := context.Background()
	c, _ := openGraph(t)
	if err := kauthz.SeedWorkspace(ctx, c, "w1", "owner"); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.SeedWorkspace(ctx, c, "w1", "owner"); err != nil {
		t.Fatalf("seed not idempotent: %v", err)
	}
	if err := kauthz.GrantResourceOwner(ctx, c, "r1", "w1", "User:creator", kauthz.OwnerRelations()); err != nil {
		t.Fatal(err)
	}
	for range 2 {
		if err := kauthz.GrantWorkspaceMembership(ctx, c, "w1", "member"); err != nil {
			t.Fatal(err)
		}
	}
	assertChecks(t, c, []expect{
		{"User:owner", kauthz.RelMembers, "Workspace:w1", true},
		{"User:member", kauthz.RelMembers, "Workspace:w1", true},
		{"User:stranger", kauthz.RelMembers, "Workspace:w1", false},
		{"User:member", kauthz.CanRead, "resource:r1", true},
		{"User:member", kauthz.CanWrite, "resource:r1", false},
		{"User:member", kauthz.CanManage, "resource:r1", false},
		{"User:owner", kauthz.CanManage, "resource:r1", true},
		{"User:owner", kauthz.CanWrite, "project:w1-root", true},
		{"User:stranger", kauthz.CanRead, "resource:r1", false},
	})
	ids, err := kauthz.WorkspaceMemberIDs(ctx, c, "w1")
	if err != nil || !slices.Equal(ids, []string{"member", "owner"}) {
		t.Fatalf("members = %v %v", ids, err)
	}
	ws, err := kauthz.MemberWorkspaceIDs(ctx, c, "member")
	if err != nil || !slices.Equal(ws, []string{"w1"}) {
		t.Fatalf("workspaces = %v %v", ws, err)
	}
	readable, err := kauthz.ReadableResourceIDs(ctx, c, "User:member")
	if _, ok := readable["r1"]; err != nil || !ok {
		t.Fatalf("readable = %v %v", readable, err)
	}

	for range 2 {
		if err := kauthz.RevokeWorkspaceMembership(ctx, c, "w1", "member"); err != nil {
			t.Fatal(err)
		}
	}
	assertChecks(t, c, []expect{
		{"User:member", kauthz.RelMembers, "Workspace:w1", false},
		{"User:member", kauthz.CanRead, "resource:r1", false},
		{"User:owner", kauthz.RelMembers, "Workspace:w1", true},
	})
	readable, err = kauthz.ReadableResourceIDs(ctx, c, "User:member")
	if err != nil || len(readable) != 0 {
		t.Fatalf("revoked member still reads %v %v", readable, err)
	}
}

func TestResourcesGrantRevokeList(t *testing.T) {
	ctx := context.Background()
	c, _ := openGraph(t)
	if err := kauthz.SeedWorkspace(ctx, c, "w1", "owner"); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"r1", "r2"} {
		if err := kauthz.GrantResourceOwner(ctx, c, id, "w1", "User:creator", kauthz.OwnerRelations()); err != nil {
			t.Fatal(err)
		}
	}
	if err := kauthz.GrantResourceOwner(ctx, c, "r1", "w1", "User:creator", kauthz.OwnerRelations()); err != nil {
		t.Fatalf("re-asserting ownership failed: %v", err)
	}
	if err := kauthz.GrantResourceOwner(ctx, c, "s1", "w1", "User:creator", kauthz.OwnerRelations()); err != nil {
		t.Fatal(err)
	}
	assertChecks(t, c, []expect{
		{"User:creator", kauthz.CanRead, "resource:r1", true},
		{"User:creator", kauthz.CanWrite, "resource:r1", true},
		{"User:creator", kauthz.CanManage, "resource:r1", true},
		{"User:creator", kauthz.CanInvoke, "resource:r1", false},
		{"User:creator", kauthz.CanUseSecret, "resource:s1", true},
		{"User:owner", kauthz.CanUseSecret, "resource:s1", true},
		{"User:owner", kauthz.CanInvoke, "resource:r1", false},
	})
	ids, err := c.ListObjects(ctx, "User:creator", kauthz.CanRead, kauthz.TypeResource)
	slices.Sort(ids)
	if err != nil || !slices.Equal(ids, []string{"r1", "r2", "s1"}) {
		t.Fatalf("list = %v %v", ids, err)
	}

	if err := kauthz.RevokeResource(ctx, c, "r1"); err != nil {
		t.Fatal(err)
	}
	left, err := c.Read(ctx, kauthz.Query{Type: kauthz.TypeResource, ID: "r1"})
	if err != nil || len(left) != 0 {
		t.Fatalf("left %v %v", left, err)
	}
	assertChecks(t, c, []expect{
		{"User:creator", kauthz.CanRead, "resource:r1", false},
		{"User:owner", kauthz.CanManage, "resource:r1", false},
		{"User:creator", kauthz.CanRead, "resource:r2", true},
	})
	ids, err = c.ListObjects(ctx, "User:creator", kauthz.CanRead, kauthz.TypeResource)
	slices.Sort(ids)
	if err != nil || !slices.Equal(ids, []string{"r2", "s1"}) {
		t.Fatalf("list after revoke = %v %v", ids, err)
	}
}

func TestAgents(t *testing.T) {
	ctx := context.Background()
	c, _ := openGraph(t)
	if err := kauthz.SeedWorkspace(ctx, c, "w1", "owner"); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.GrantWorkspaceMembership(ctx, c, "w1", "member"); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.GrantResourceOwner(ctx, c, "a1", "w1", "User:creator", kauthz.AgentOwnerRelations()); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.EnrollAgent(ctx, c, "a1", "w1"); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.GrantResourceOwner(ctx, c, "r1", "w1", "User:creator", kauthz.OwnerRelations()); err != nil {
		t.Fatal(err)
	}
	assertChecks(t, c, []expect{
		{"User:creator", kauthz.CanInvoke, "resource:a1", true},
		{"Agent:a1", kauthz.CanInvoke, "resource:a1", true},
		{"Agent:a1", kauthz.RelMembers, "Workspace:w1", true},
		{"Agent:a1", kauthz.CanRead, "resource:r1", true},
		{"Agent:a1", kauthz.CanWrite, "resource:r1", false},
		{"User:member", kauthz.CanRead, "resource:a1", true},
		{"User:member", kauthz.CanInvoke, "resource:a1", false},
		{"User:owner", kauthz.CanManage, "resource:a1", true},
		{"User:owner", kauthz.CanInvoke, "resource:a1", false},
	})
	everyone := kauthz.Tuple{User: "Workspace:w1#members", Relation: kauthz.RelInvoker, Object: "resource:a1"}
	if changed, err := kauthz.WriteIdempotent(ctx, c, everyone); err != nil || !changed {
		t.Fatalf("grant to members: %v %v", changed, err)
	}
	assertChecks(t, c, []expect{
		{"User:member", kauthz.CanInvoke, "resource:a1", true},
		{"User:stranger", kauthz.CanInvoke, "resource:a1", false},
	})
	tuples, err := c.Read(ctx, kauthz.Query{Type: kauthz.TypeResource, ID: "a1", Relation: kauthz.RelInvoker})
	if err != nil || !slices.Contains(tuples, everyone) {
		t.Fatalf("userset tuple read back as %v %v", tuples, err)
	}

	for range 2 {
		if err := kauthz.WithdrawAgent(ctx, c, "a1", "w1"); err != nil {
			t.Fatal(err)
		}
	}
	assertChecks(t, c, []expect{
		{"Agent:a1", kauthz.RelMembers, "Workspace:w1", false},
		{"Agent:a1", kauthz.CanRead, "resource:r1", false},
		{"Agent:a1", kauthz.CanInvoke, "resource:a1", false},
	})
}

func TestConnectionsPersonalAndShared(t *testing.T) {
	ctx := context.Background()
	c, _ := openGraph(t)
	if err := kauthz.SeedWorkspace(ctx, c, "w1", "owner"); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.GrantWorkspaceMembership(ctx, c, "w1", "member"); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.GrantResourceOwner(ctx, c, "c1", "w1", "User:creator", kauthz.OwnerRelations()); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.MakePersonal(ctx, c, "c1"); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.LendConnection(ctx, c, "c1", "a1"); err != nil {
		t.Fatal(err)
	}
	assertChecks(t, c, []expect{
		{"User:creator", kauthz.CanUseConnection, "resource:c1", true},
		{"Agent:a1", kauthz.CanUseConnection, "resource:c1", true},
		{"User:member", kauthz.CanRead, "resource:c1", true},
		{"User:member", kauthz.CanUseConnection, "resource:c1", false},
		{"User:owner", kauthz.CanManage, "resource:c1", true},
		{"User:owner", kauthz.CanUseConnection, "resource:c1", false},
	})
	personal, err := kauthz.PersonalConnectionIDs(ctx, c, []string{"c1", "c2"})
	if _, ok := personal["c1"]; err != nil || !ok || len(personal) != 1 {
		t.Fatalf("personal = %v %v", personal, err)
	}
	owner, err := kauthz.IsConnectionOwner(ctx, c, "User:creator", "c1")
	if err != nil || !owner {
		t.Fatalf("creator not owner: %v", err)
	}
	if owner, _ := kauthz.IsConnectionOwner(ctx, c, "User:owner", "c1"); owner {
		t.Error("workspace admin counted as connection owner")
	}

	for range 2 {
		if err := kauthz.ShareWithWorkspace(ctx, c, "c1"); err != nil {
			t.Fatal(err)
		}
	}
	if err := kauthz.WithdrawConnection(ctx, c, "c1", "a1"); err != nil {
		t.Fatal(err)
	}
	assertChecks(t, c, []expect{
		{"User:member", kauthz.CanUseConnection, "resource:c1", true},
		{"User:owner", kauthz.CanUseConnection, "resource:c1", true},
		{"Agent:a1", kauthz.CanUseConnection, "resource:c1", false},
	})
}

// The idempotency rules match the server's own messages for an existing
// tuple and a missing one.
func TestIdempotencyAgainstServer(t *testing.T) {
	ctx := context.Background()
	c, _ := openGraph(t)
	tu := kauthz.Tuple{User: "User:u1", Relation: kauthz.RelReader, Object: "resource:r1"}
	for i, want := range []bool{true, false} {
		if changed, err := kauthz.WriteIdempotent(ctx, c, tu); err != nil || changed != want {
			t.Fatalf("write %d: %v %v", i, changed, err)
		}
	}
	for i, want := range []bool{true, false} {
		if changed, err := kauthz.DeleteIdempotent(ctx, c, tu); err != nil || changed != want {
			t.Fatalf("delete %d: %v %v", i, changed, err)
		}
	}
	bad := kauthz.Tuple{User: "User:u1", Relation: "no_such_relation", Object: "resource:r1"}
	var oe *kauthz.OwnershipError
	if _, err := kauthz.WriteIdempotent(ctx, c, bad); !errors.As(err, &oe) {
		t.Fatalf("invalid tuple: %v", err)
	}
	var re *kauthz.ResponseError
	if _, err := c.Check(ctx, "User:u1", "no_such_relation", "resource", "r1"); !errors.As(err, &re) || re.Status != 400 {
		t.Fatalf("check of an unknown relation: %v", err)
	}
	if err := c.Write(ctx, []kauthz.Tuple{tu, tu}, nil); err == nil {
		t.Fatal("duplicate tuples in one write accepted")
	}
}

func TestBatchCheckChunks(t *testing.T) {
	ctx := context.Background()
	c, _ := openGraph(t)
	var writes []kauthz.Tuple
	var items []kauthz.CheckItem
	for i := range 300 {
		id := fmt.Sprintf("r%03d", i)
		if i%3 == 0 {
			writes = append(writes, kauthz.Tuple{User: "User:u1", Relation: kauthz.RelReader, Object: "resource:" + id})
		}
		items = append(items, kauthz.CheckItem{Subject: "User:u1", Relation: kauthz.CanRead, ObjectType: kauthz.TypeResource, ObjectID: id})
	}
	for start := 0; start < len(writes); start += 20 {
		if err := c.Write(ctx, writes[start:min(start+20, len(writes))], nil); err != nil {
			t.Fatal(err)
		}
	}
	got, err := c.BatchCheck(ctx, items)
	if err != nil {
		t.Fatal(err)
	}
	for i, ok := range got {
		if ok != (i%3 == 0) {
			t.Errorf("item %d = %v", i, ok)
		}
	}
	tuples, err := c.Read(ctx, kauthz.Query{Type: kauthz.TypeResource, User: "User:u1"})
	if err != nil || len(tuples) != len(writes) {
		t.Fatalf("paged read returned %d of %d: %v", len(tuples), len(writes), err)
	}
}

func TestUnreachableGraphFailsClosed(t *testing.T) {
	c, err := NewClient("http://127.0.0.1:1", pyStore, "", "", time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	var ue *kauthz.UnavailableError
	if ok, err := c.Check(ctx, "User:u1", kauthz.CanRead, "resource", "r1"); ok || !errors.As(err, &ue) {
		t.Fatalf("check = %v %v", ok, err)
	}
	if _, err := kauthz.ReadableResourceIDs(ctx, c, "User:u1"); !errors.As(err, &ue) {
		t.Fatalf("list = %v", err)
	}
	if ok, err := c.BatchCheck(ctx, []kauthz.CheckItem{{Subject: "User:u1", Relation: kauthz.CanRead, ObjectType: "resource", ObjectID: "r1"}}); ok != nil || !errors.As(err, &ue) {
		t.Fatalf("batch = %v %v", ok, err)
	}
}

func TestRedirectIsNotFollowed(t *testing.T) {
	var hits int
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
		_, _ = w.Write([]byte(`{"allowed":true}`))
	}))
	defer target.Close()
	redirect := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL+r.URL.Path, http.StatusTemporaryRedirect)
	}))
	defer redirect.Close()
	c, err := NewClient(redirect.URL, pyStore, "", "secret", time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	var re *kauthz.ResponseError
	if ok, err := c.Check(context.Background(), "User:u1", kauthz.CanRead, "resource", "r1"); ok || !errors.As(err, &re) || re.Status != http.StatusTemporaryRedirect {
		t.Fatalf("check = %v %v", ok, err)
	}
	if hits != 0 {
		t.Fatal("redirect followed")
	}
}
