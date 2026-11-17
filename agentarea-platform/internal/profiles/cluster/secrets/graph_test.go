package secrets

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"slices"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	kauthz "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	clusterauthz "github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/authz"
)

type memGraph struct {
	mu     sync.Mutex
	tuples []kauthz.Tuple
	checks []string
	allow  bool
	err    error
}

func (g *memGraph) Check(_ context.Context, subject, relation, objectType, objectID string) (bool, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.checks = append(g.checks, subject+" "+relation+" "+objectType+":"+objectID)
	return g.allow, g.err
}

func (g *memGraph) Read(_ context.Context, q kauthz.Query) ([]kauthz.Tuple, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	var out []kauthz.Tuple
	for _, t := range g.tuples {
		if t.Object == kauthz.ObjectRef(q.Type, q.ID) {
			out = append(out, t)
		}
	}
	return out, nil
}

func (g *memGraph) Write(_ context.Context, writes, deletes []kauthz.Tuple) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.tuples = append(g.tuples, writes...)
	g.tuples = slices.DeleteFunc(g.tuples, func(t kauthz.Tuple) bool { return slices.Contains(deletes, t) })
	return nil
}

func TestGuardAsksUseSecretOnTheResource(t *testing.T) {
	ctx := context.Background()
	g := &memGraph{allow: true}
	guard := NewGuard(kauthz.NewPermissions(g, quietLogger()))
	if ok, err := guard.CanUseSecret(ctx, "User:u1", "s1"); err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	g.allow = false
	if ok, err := guard.CanUseSecret(ctx, "User:u1", "s1"); err != nil || ok {
		t.Errorf("a refusal read as allowed: %v %v", ok, err)
	}
	g.err = errors.New("graph down")
	if ok, err := guard.CanUseSecret(ctx, "User:u1", "s1"); err == nil || ok {
		t.Errorf("a graph failure read as an answer: %v %v", ok, err)
	}
	want := "User:u1 " + kauthz.CanUseSecret + " " + kauthz.TypeResource + ":s1"
	if len(g.checks) != 3 || g.checks[0] != want {
		t.Errorf("checks %v, want %q", g.checks, want)
	}
}

func TestOwnershipGrantsAndRevokes(t *testing.T) {
	ctx := context.Background()
	g := &memGraph{}
	o := NewOwnership(g)
	if err := o.GrantOwner(ctx, "s1", "w1", "User:u1"); err != nil {
		t.Fatal(err)
	}
	object := kauthz.ObjectRef(kauthz.TypeResource, "s1")
	want := []kauthz.Tuple{
		{User: kauthz.RootProject("w1"), Relation: kauthz.RelProject, Object: object},
		{User: "User:u1", Relation: kauthz.RelReader, Object: object},
		{User: "User:u1", Relation: kauthz.RelWriter, Object: object},
		{User: "User:u1", Relation: kauthz.RelManager, Object: object},
	}
	if !slices.Equal(g.tuples, want) {
		t.Errorf("tuples %v, want %v", g.tuples, want)
	}
	if err := o.Revoke(ctx, "s1"); err != nil {
		t.Fatal(err)
	}
	if len(g.tuples) != 0 {
		t.Errorf("left %v", g.tuples)
	}
}

// TestGraphGovernsSecretUse runs Guard and Ownership on the packaged model.
func TestGraphGovernsSecretUse(t *testing.T) {
	url := os.Getenv("AGENTAREA_TEST_OPENFGA_URL")
	if url == "" {
		t.Skip("AGENTAREA_TEST_OPENFGA_URL is not set")
	}
	ctx := context.Background()
	c, _, err := clusterauthz.Open(ctx, kauthz.Config{
		Backend: "openfga", URL: url, Timeout: 10 * time.Second, Bootstrap: true, ApplyModel: true,
		StoreName: "aa-go-secrets-" + strconv.FormatInt(time.Now().UnixNano(), 36),
	}, clusterauthz.Options{Log: quietLogger()})
	if err != nil {
		t.Fatal(err)
	}
	ws, secret := uuid.NewString(), uuid.NewString()
	if err := kauthz.SeedWorkspace(ctx, c, ws, "admin"); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.GrantWorkspaceMembership(ctx, c, ws, "member"); err != nil {
		t.Fatal(err)
	}
	if err := kauthz.GrantWorkspaceMembership(ctx, c, ws, "creator"); err != nil {
		t.Fatal(err)
	}
	owners := NewOwnership(c)
	if err := owners.GrantOwner(ctx, secret, ws, kauthz.UserSubject("creator")); err != nil {
		t.Fatal(err)
	}
	guard := NewGuard(kauthz.NewPermissions(c, quietLogger()))
	for subject, want := range map[string]bool{"creator": true, "admin": true, "member": false, "stranger": false} {
		ok, err := guard.CanUseSecret(ctx, kauthz.UserSubject(subject), secret)
		if err != nil || ok != want {
			t.Errorf("%s: %v %v, want %v", subject, ok, err, want)
		}
	}
	if err := owners.Revoke(ctx, secret); err != nil {
		t.Fatal(err)
	}
	if ok, err := guard.CanUseSecret(ctx, kauthz.UserSubject("creator"), secret); err != nil || ok {
		t.Errorf("after revoke: %v %v", ok, err)
	}
}

func quietLogger() *slog.Logger { return slog.New(slog.DiscardHandler) }
