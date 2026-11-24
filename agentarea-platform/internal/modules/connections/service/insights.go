package service

import (
	"context"
	"math"
	"slices"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store"
)

// ConnectionBoard implements api.ConnectionBoard over the read pool.
type ConnectionBoard struct {
	DB db.Database
}

var _ api.ConnectionBoard = ConnectionBoard{}

func (b ConnectionBoard) read(ctx context.Context, ws scope.Workspace, fn func(s db.Session) error) error {
	s, release, err := b.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(s)
}

func (b ConnectionBoard) instances(ctx context.Context, ws scope.Workspace) ([]api.MCPInstanceState, error) {
	var out []api.MCPInstanceState
	err := b.read(ctx, ws, func(s db.Session) error {
		rows, err := store.Instances{}.List(ctx, s)
		if err != nil {
			return err
		}
		scopes, err := store.New(s.Q()).InstanceNetworkScopes(ctx, ws.ID())
		if err != nil {
			return err
		}
		scopeOf := make(map[string]string, len(scopes))
		for _, r := range scopes {
			scopeOf[r.ID.String()] = r.NetworkScope
		}
		for _, i := range rows {
			out = append(out, api.MCPInstanceState{
				ID: i.ID, WorkspaceID: i.WorkspaceID, Name: i.Name, ServerSpecID: i.ServerSpecID, NetworkScope: scopeOf[i.ID],
				ToolCount: len(i.AvailableTools()), JSONSpec: i.JSONSpec, Verification: i.VerificationRaw,
				LastDispatch: i.LastDispatch, Platform: i.PlatformManaged(),
			})
		}
		return nil
	})
	return out, err
}

func failed(state map[string]any) bool {
	s, _ := state["status"].(string)
	return s == "failed"
}

// FailingMCPInstances implements api.ConnectionBoard.
func (b ConnectionBoard) FailingMCPInstances(ctx context.Context, ws scope.Workspace, limit int) ([]api.MCPInstanceState, error) {
	all, err := b.instances(ctx, ws)
	if err != nil {
		return nil, err
	}
	var out []api.MCPInstanceState
	for _, i := range all {
		if i.WorkspaceID == ws.ID() && (failed(i.Verification) || failed(i.LastDispatch)) {
			out = append(out, i)
		}
	}
	slices.SortStableFunc(out, func(a, b api.MCPInstanceState) int { return strings.Compare(a.Name, b.Name) })
	return out[:min(len(out), max(limit, 0))], nil
}

// MCPInstances implements api.ConnectionBoard.
func (b ConnectionBoard) MCPInstances(ctx context.Context, ws scope.Workspace) ([]api.MCPInstanceState, error) {
	return b.instances(ctx, ws)
}

// OpenAPIConnections implements api.ConnectionBoard.
func (b ConnectionBoard) OpenAPIConnections(ctx context.Context, ws scope.Workspace) ([]api.OpenAPIState, error) {
	var out []api.OpenAPIState
	err := b.read(ctx, ws, func(s db.Session) error {
		rows, err := store.OpenAPI{}.List(ctx, s, store.Filter{}, math.MaxInt32, 0)
		if err != nil {
			return err
		}
		for _, c := range rows {
			if c.WorkspaceID != ws.ID() {
				continue
			}
			out = append(out, openAPIState(c))
		}
		return nil
	})
	return out, err
}

func openAPIState(c domain.Connection) api.OpenAPIState {
	return api.OpenAPIState{ID: c.ID, Name: c.Name, Description: c.Description, Status: c.Status,
		BaseURL: c.VisibleBaseURL(), ToolCount: len(c.AvailableTools)}
}
