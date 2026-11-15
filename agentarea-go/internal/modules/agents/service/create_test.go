package service

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

type createFakeConnections struct {
	fail error
	lent []string
}

func (f *createFakeConnections) BindMCPName(context.Context, authn.Caller, string, bool) (string, error) {
	return "", nil
}

func (f *createFakeConnections) Lend(_ context.Context, connectionID, agentID string) error {
	if f.fail != nil {
		return f.fail
	}
	f.lent = append(f.lent, connectionID+">"+agentID)
	return nil
}

func (f *createFakeConnections) Withdraw(context.Context, string, string) error { return nil }

func createAgents(t *testing.T, s *Service, d db.Database, c authn.Caller) []domain.Agent {
	t.Helper()
	sess, release, err := d.Read(context.Background(), c.Workspace)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	all, err := s.store.List(context.Background(), sess)
	if err != nil {
		t.Fatal(err)
	}
	return all
}

func TestCreateRollsBackWhenTheLoanFails(t *testing.T) {
	d, g, s, c := clientSetup(t)
	conn := uuid.NewString()
	g.objects[conn] = true
	in := Create{Name: "Lender", AgentType: "standard", Tools: []domain.Tool{
		{Type: domain.ToolOpenAPI, Name: "api", Settings: &domain.Settings{OpenAPIConnectionID: &conn}}}}

	var unwired *UnwiredError
	if _, err := s.Create(context.Background(), c, in); !errors.As(err, &unwired) {
		t.Fatalf("no connections port: %v", err)
	}
	if got := createAgents(t, s, d, c); len(got) != 0 {
		t.Fatalf("an unwired loan left %d agents", len(got))
	}

	boom := errors.New("graph down")
	conns := &createFakeConnections{fail: boom}
	s.UseConnections(conns)
	if _, err := s.Create(context.Background(), c, in); !errors.Is(err, boom) {
		t.Fatalf("failed loan: %v", err)
	}
	if got := createAgents(t, s, d, c); len(got) != 0 {
		t.Fatalf("a failed loan left %d agents", len(got))
	}

	conns.fail = nil
	v, err := s.Create(context.Background(), c, in)
	if err != nil {
		t.Fatal(err)
	}
	if got := createAgents(t, s, d, c); len(got) != 1 || got[0].ID != v.Agent.ID {
		t.Fatalf("agents %+v", got)
	}
	if len(conns.lent) != 1 || conns.lent[0] != conn+">"+v.Agent.ID {
		t.Fatalf("lent %v", conns.lent)
	}
}
