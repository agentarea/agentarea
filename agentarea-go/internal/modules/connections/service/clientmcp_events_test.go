package service

import (
	"context"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

func TestClientCallerIsTheClientsWorkspace(t *testing.T) {
	f := newClientFixture(t, nil)
	ctx := context.Background()

	c, ok, err := f.svc.ClientCaller(ctx, workspaceMember(), f.clientID, enterClientWS)
	if err != nil || !ok || c.Workspace.ID() != clientWS || c.UserID != "u1" {
		t.Fatalf("member: %+v %v %v", c, ok, err)
	}

	outsider := authn.Principal{UserID: "u2", AccessibleWorkspaces: []string{"33333333-3333-3333-3333-333333333333"}}
	for name, call := range map[string]func() (authn.Caller, bool, error){
		"outsider": func() (authn.Caller, bool, error) {
			return f.svc.ClientCaller(ctx, outsider, f.clientID, enterClientWS)
		},
		"not a uuid": func() (authn.Caller, bool, error) {
			return f.svc.ClientCaller(ctx, workspaceMember(), "x", enterClientWS)
		},
	} {
		if _, ok, err := call(); ok || err != nil {
			t.Fatalf("%s: %v %v", name, ok, err)
		}
	}

	g := useGraph{readable: map[string]bool{}}
	f.svc.d.Graph = g
	f.svc.perms = New(Deps{Graph: g}).perms
	if _, ok, err := f.svc.ClientCaller(ctx, workspaceMember(), f.clientID, enterClientWS); ok || err != nil {
		t.Fatalf("unauthorized: %v %v", ok, err)
	}
}
