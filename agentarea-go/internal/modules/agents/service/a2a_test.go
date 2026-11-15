package service

import (
	"context"
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

func TestA2AAllowed(t *testing.T) {
	agent := domain.Agent{ID: "a1", WorkspaceID: "w1"}
	for name, c := range map[string]struct {
		p    *authn.Principal
		want bool
	}{
		"anonymous":            {nil, false},
		"member":               {&authn.Principal{UserID: "u", AccessibleWorkspaces: []string{"w1"}}, true},
		"outsider":             {&authn.Principal{UserID: "u", AccessibleWorkspaces: []string{"w2"}}, false},
		"own key":              {&authn.Principal{UserID: "u", BoundAgentID: "a1", BoundWorkspaceID: "w1"}, true},
		"key of another agent": {&authn.Principal{UserID: "u", BoundAgentID: "a2", BoundWorkspaceID: "w1", AccessibleWorkspaces: []string{"w1"}}, false},
		"key of another ws":    {&authn.Principal{UserID: "u", BoundAgentID: "a1", BoundWorkspaceID: "w2"}, false},
	} {
		if got := a2aAllowed(c.p, agent); got != c.want {
			t.Errorf("%s: %v", name, got)
		}
	}
}

func TestA2ACallerOfAnAgentKey(t *testing.T) {
	adm := A2AAdmission{
		Principal: &authn.Principal{UserID: "u", BoundAgentID: "a1", BoundWorkspaceID: "w1"},
		Auth:      domain.A2AAuth{Authenticated: true, UserID: "u", WorkspaceID: "w1", AgentKeyID: "k1"},
	}
	c, err := a2aCaller(adm)
	if err != nil {
		t.Fatal(err)
	}
	if c.Workspace.ID() != "w1" || c.AdminWorkspaces == nil || len(c.AdminWorkspaces) != 0 || c.Credential.KeyID != "k1" || c.Credential.Kind != authn.KindAPIKey {
		t.Errorf("%+v", c)
	}
	var rpc *domain.A2ARPCError
	if _, err := a2aCaller(A2AAdmission{}); !errors.As(err, &rpc) || rpc.Message != "A2A requests require an authenticated user" {
		t.Errorf("anonymous: %v", err)
	}
}

type a2aFakeTasks struct{ got A2ACall }

func (f *a2aFakeTasks) Handle(_ context.Context, call A2ACall) (domain.A2AJSON, error) {
	f.got = call
	if call.Method == "CancelTask" {
		return nil, &domain.A2ARPCError{Code: domain.A2ACodeTaskNotFound, Message: "Task not found"}
	}
	return domain.A2AJSON{{Key: "id", Value: "t1"}}, nil
}

func TestA2ADispatchRoutesTaskMethods(t *testing.T) {
	ctx := context.Background()
	member := &authn.Principal{UserID: "u", AccessibleWorkspaces: []string{"w1"}}
	adm := A2AAdmission{
		Agent: domain.Agent{ID: "7d1c1b9e-3c2a-4f7e-9a51-0e7d2f3b4c5d", WorkspaceID: "w1"}, Principal: member,
		Auth: domain.A2AAuth{Authenticated: true, UserID: "u", WorkspaceID: "w1"},
	}
	unwired := NewA2A(&Service{}, A2APorts{})
	got, _ := unwired.Dispatch(ctx, adm, "rpc", domain.A2ARPCRequest{ID: "1", Method: "GetTask"}, "1.0")
	if e, _ := got.Get("error"); e == nil {
		t.Fatalf("unwired GetTask answered %v", got)
	}
	tasks := &a2aFakeTasks{}
	wired := NewA2A(&Service{}, A2APorts{Tasks: tasks})
	got, _ = wired.Dispatch(ctx, adm, "rpc", domain.A2ARPCRequest{ID: "1", Method: "GetTask", Params: domain.A2AJSON{{Key: "id", Value: "t1"}}, HasParams: true}, "1.0")
	if r, _ := got.Get("result"); r == nil || tasks.got.Method != "GetTask" || tasks.got.Caller.Workspace.ID() != "w1" || tasks.got.RPCURL != "rpc" {
		t.Errorf("%v %+v", got, tasks.got)
	}
	got, _ = wired.Dispatch(ctx, adm, "rpc", domain.A2ARPCRequest{ID: "2", Method: "CancelTask"}, "1.0")
	if e, _ := got.Get("error"); e == nil {
		t.Errorf("%v", got)
	}
	got, _ = wired.Dispatch(ctx, adm, "rpc", domain.A2ARPCRequest{ID: "3", Method: "SendStreamingMessage"}, "1.0")
	if e, _ := got.Get("error"); e.(domain.A2AJSON)[1].Value != "SendStreamingMessage is not available yet" {
		t.Errorf("%v", got)
	}
}

func TestA2APortsUnwired(t *testing.T) {
	a := NewA2A(&Service{}, A2APorts{})
	var unwired *UnwiredError
	if _, err := a.ReadCard(context.Background(), "http://peer"); !errors.As(err, &unwired) {
		t.Errorf("card: %v", err)
	}
	if _, err := a.Principal(context.Background(), "tok"); !errors.As(err, &unwired) {
		t.Errorf("principal: %v", err)
	}
	if p, err := a.Principal(context.Background(), ""); p != nil || err != nil {
		t.Errorf("no token: %v %v", p, err)
	}
	if err := a.Limit(context.Background(), "ip:1"); err != nil {
		t.Errorf("limit: %v", err)
	}
}

func (f *a2aFakeTasks) Stream(context.Context, A2ACall, func(domain.A2AJSON) error) error {
	return domain.A2AUnavailable("stream")
}

func TestA2ACallerOfAPersonalKeyIsNoAgentKey(t *testing.T) {
	adm := A2AAdmission{
		Principal: &authn.Principal{UserID: "u", BoundWorkspaceID: "w1", AccessibleWorkspaces: []string{"w1"},
			Credential: &authn.Credential{Kind: authn.KindAPIKey, KeyID: "personal"}},
		Auth: domain.A2AAuth{Authenticated: true, UserID: "u", WorkspaceID: "w1"},
	}
	c, err := a2aCaller(adm)
	if err != nil {
		t.Fatal(err)
	}
	if c.Credential != nil {
		t.Errorf("a personal key passes as an agent key: %+v", c.Credential)
	}
}
