package service

import (
	"context"
	"errors"
	"math"
	"net/http"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
)

func TestA2AStartAsksExecuteOfAnyKeyButTheAgentsOwn(t *testing.T) {
	s, p, _, _, _, _ := createSurface(t)
	denied := errors.New("Permission denied")
	var asked []string
	s.d.Permissions = func(_ context.Context, _ authn.Caller, permission, _, id string) error {
		asked = append(asked, permission+" "+id)
		return denied
	}
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "ws")
	key := func(bound string) context.Context {
		return authn.WithCaller(context.Background(), authn.Caller{Principal: authn.Principal{
			UserID: p.UserID, BoundWorkspaceID: p.WorkspaceID, BoundAgentID: bound,
			Credential: &authn.Credential{Kind: authn.KindAPIKey, KeyID: "k"},
		}, Workspace: ws})
	}
	if _, err := s.A2A().Start(key(""), agentsapi.A2AStart{AgentID: p.AgentID, Description: "go"}); !errors.Is(err, denied) {
		t.Fatalf("a personal key without execute started a run: %v", err)
	}
	if _, err := s.A2A().Start(key(p.AgentID), agentsapi.A2AStart{AgentID: p.AgentID, Description: "go"}); err != nil {
		t.Fatalf("the agent's own key: %v", err)
	}
	if len(asked) != 1 || asked[0] != "execute "+p.AgentID {
		t.Fatalf("asked %v", asked)
	}
}

func TestA2AAgentTasksRefusesAnOffsetPastInt32(t *testing.T) {
	s, p, _, _, _, ctx := createSurface(t)
	_, _, err := s.A2A().AgentTasks(ctx, p.AgentID, 10, math.MaxInt32+1)
	if he := (*httpx.Error)(nil); !errors.As(err, &he) || he.Status != http.StatusBadRequest {
		t.Fatalf("an offset past int32: %v", err)
	}
	if _, _, err := s.A2A().AgentTasks(ctx, p.AgentID, 10, math.MaxInt32); err != nil {
		t.Fatal(err)
	}
}
