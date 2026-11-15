package handlers

import (
	"context"
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

func TestToolsetDocumentValidatesLikeTheRoute(t *testing.T) {
	in, err := toolsetDocument([]byte(`{"name":" A ","tools":[]}`), createBody)
	if err != nil || in.create.Name != "A" {
		t.Fatal(in.create, err)
	}
	if _, err := toolsetDocument([]byte(`{"name":"A"}`), createBody); err == nil {
		t.Error("tools is required")
	}
	if _, err := toolsetDocument([]byte(`{"description":null}`), updateBody); err != nil {
		t.Error(err)
	}
}

func TestToolsetRefusesNonUUIDBeforeTheService(t *testing.T) {
	ts := AgentsToolset{}
	c := authn.Caller{}
	if _, err := ts.Get(context.Background(), c, "slug"); err == nil {
		t.Error("Get")
	}
	if err := ts.Archive(context.Background(), c, "slug"); err == nil {
		t.Error("Archive")
	}
	if !errors.Is(toolsetNotFound(domain.ErrAgentNotFound), api.ErrNotFound) {
		t.Error("not found mapping")
	}
}
