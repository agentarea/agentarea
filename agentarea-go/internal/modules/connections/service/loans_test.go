package service

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
)

type namedStore map[string][]store.NamedInstance

func (n namedStore) MCPInstancesNamed(_ context.Context, _ db.Session, name string) ([]store.NamedInstance, error) {
	return n[name], nil
}

type tupleLog struct{ writes, deletes []authz.Tuple }

func (t *tupleLog) Write(_ context.Context, w, d []authz.Tuple) error {
	t.writes, t.deletes = append(t.writes, w...), append(t.deletes, d...)
	return nil
}

func TestBindMCPName(t *testing.T) {
	ws, _ := scope.NewWorkspace(uuid.NewString(), "w")
	c := authn.Caller{Principal: authn.Principal{UserID: "me"}, Workspace: ws}
	platform := "platform"
	mine, theirs, plat, dup := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	l := Loans{DB: memDB{}, Store: namedStore{
		"mine":   {{ID: mine, CreatedBy: "me"}},
		"theirs": {{ID: theirs, CreatedBy: "you"}},
		"plat":   {{ID: plat, CreatedBy: "ops", ManagedBy: &platform}},
		"dup":    {{ID: dup, CreatedBy: "me"}, {ID: uuid.New(), CreatedBy: "me"}},
	}}
	for name, want := range map[string]string{"mine": mine.String(), "plat": plat.String(), "none": ""} {
		if got, err := l.BindMCPName(context.Background(), c, name, true); err != nil || got != want {
			t.Errorf("%s: %q %v", name, got, err)
		}
	}
	for name, detail := range map[string]string{
		"theirs": "the MCP connection named 'theirs' was added by someone else; name the one to use by its id.",
		"dup":    "2 MCP connections here are named 'dup'; name the one to use by its id.",
	} {
		var ne *api.MCPNameError
		if _, err := l.BindMCPName(context.Background(), c, name, true); !errors.As(err, &ne) || ne.Detail != detail {
			t.Errorf("%s: %v", name, err)
		}
		if got, err := l.BindMCPName(context.Background(), c, name, false); err != nil || got != "" {
			t.Errorf("%s kept: %q %v", name, got, err)
		}
	}
}

func TestLendAndWithdrawWriteTheLoan(t *testing.T) {
	g := &tupleLog{}
	l := Loans{Graph: g}
	if err := l.Lend(context.Background(), "c1", "a1"); err != nil {
		t.Fatal(err)
	}
	if err := l.Withdraw(context.Background(), "c1", "a1"); err != nil {
		t.Fatal(err)
	}
	want := authz.Tuple{User: "Agent:a1", Relation: "connection_user", Object: "resource:c1"}
	if len(g.writes) != 1 || g.writes[0] != want || len(g.deletes) != 1 || g.deletes[0] != want {
		t.Fatalf("writes %+v deletes %+v", g.writes, g.deletes)
	}
}
