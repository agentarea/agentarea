package service

import (
	"context"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

func TestWorkspaceOwner(t *testing.T) {
	st := &fakeStore{workspaces: map[string]domain.Workspace{"w1": {ID: "w1", OwnerUserID: "u-owner"}}}
	o := WorkspaceOwners{DB: fakeDB{}, Store: st}
	if id, ok, err := o.Owner(context.Background(), "w1"); err != nil || !ok || id != "u-owner" {
		t.Fatalf("owner: %q %v %v", id, ok, err)
	}
	if id, ok, err := o.Owner(context.Background(), "gone"); err != nil || ok || id != "" {
		t.Fatalf("missing workspace: %q %v %v", id, ok, err)
	}
}
