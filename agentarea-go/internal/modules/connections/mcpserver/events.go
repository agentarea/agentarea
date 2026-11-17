package mcpserver

import (
	"context"
	"errors"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

// Events is the MCP Events extension the platform mounts serve (mcp_events.install_mcp_events):
// Server answers the events methods, Members lists the workspaces a spanning caller reaches.
type Events struct {
	Server  streamsapi.MCPEvents
	Members identityapi.Members
}

// EventsHandler serves the events methods on an endpoint; Scope is the workspaces the request reaches.
type EventsHandler struct {
	Server streamsapi.MCPEvents
	Scope  func(r *http.Request) (streamsapi.EventsScope, error)
}

func eventsSettings() map[string]any { return map[string]any{"listChanged": false} }

// UseEvents serves the events extension on the platform's mounts; nil serves none.
func (p *Platform) UseEvents(e *Events) { p.events = e }

func (p *Platform) eventsHandler() *EventsHandler {
	if p.events == nil {
		return nil
	}
	return &EventsHandler{Server: p.events.Server, Scope: func(r *http.Request) (streamsapi.EventsScope, error) {
		if !p.spanning {
			c, ok := authn.CallerFrom(r.Context())
			if !ok {
				return nil, authn.ErrWorkspaceNotSelected
			}
			return pinnedScope{c: c}, nil
		}
		prin, ok := authn.PrincipalFrom(r.Context())
		if !ok {
			return nil, authn.ErrNoPrincipal
		}
		return spanningScope{p: prin, gate: p.auth.Gate, members: p.events.Members}, nil
	}}
}

func noSuchEventTypeHere() error {
	return &streamsapi.EventsError{Code: streamsapi.EventsNotFound, Message: "no such event type here", Data: map[string]any{"kind": "event"}}
}

// pinnedScope is /mcp/w/{workspace}: the workspace the URL pinned.
type pinnedScope struct{ c authn.Caller }

func (s pinnedScope) Workspaces(context.Context) ([]authn.Caller, error) {
	return []authn.Caller{s.c}, nil
}

func (s pinnedScope) Enter(_ context.Context, workspace string) (authn.Caller, error) {
	if workspace != s.c.Workspace.Slug() && workspace != s.c.Workspace.ID() {
		return authn.Caller{}, noSuchEventTypeHere()
	}
	return s.c, nil
}

// spanningScope is /mcp: every workspace the caller reaches; the event name says which.
type spanningScope struct {
	p       authn.Principal
	gate    authn.Gate
	members identityapi.Members
}

func (s spanningScope) Workspaces(ctx context.Context) ([]authn.Caller, error) {
	reachable, err := s.members.ListWorkspaces(ctx, s.p)
	if err != nil {
		return nil, err
	}
	out := make([]authn.Caller, 0, len(reachable))
	for _, ws := range reachable {
		c, err := s.gate.EnterWorkspace(ctx, s.p, ws.ID)
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, nil
}

func (s spanningScope) Enter(ctx context.Context, workspace string) (authn.Caller, error) {
	c, err := s.gate.EnterWorkspace(ctx, s.p, workspace)
	var unreachable *scope.UnreachableError
	if errors.As(err, &unreachable) {
		return authn.Caller{}, &streamsapi.EventsError{Code: streamsapi.EventsForbidden, Message: "no accessible workspace " + domain.PyRepr(workspace)}
	}
	return c, err
}

// ClientEventsScope is /mcp/clients/{id}: the client's workspace, as its caller. resolve is the
// caller there, false when the caller reaches no such client or may not use it.
func ClientEventsScope(resolve func(ctx context.Context) (authn.Caller, bool, error)) streamsapi.EventsScope {
	return clientScope{resolve: resolve}
}

type clientScope struct {
	resolve func(ctx context.Context) (authn.Caller, bool, error)
}

func (s clientScope) caller(ctx context.Context) (authn.Caller, error) {
	c, ok, err := s.resolve(ctx)
	if err != nil {
		return authn.Caller{}, err
	}
	if !ok {
		return authn.Caller{}, &streamsapi.EventsError{Code: streamsapi.EventsForbidden, Message: "not authorized for this client"}
	}
	return c, nil
}

func (s clientScope) Workspaces(ctx context.Context) ([]authn.Caller, error) {
	c, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	return []authn.Caller{c}, nil
}

func (s clientScope) Enter(ctx context.Context, workspace string) (authn.Caller, error) {
	c, err := s.caller(ctx)
	if err != nil {
		return authn.Caller{}, err
	}
	return pinnedScope{c: c}.Enter(ctx, workspace)
}

func (e *Endpoint) serveEvents(r *http.Request, req Request, modern bool) (any, *Error) {
	ctx := r.Context()
	s, err := e.Events.Scope(r)
	if err != nil {
		return nil, e.rpcError(ctx, req.Method, err, modern)
	}
	res, err := e.Events.Server.Serve(ctx, s, req.Method, req.Params)
	var refused *streamsapi.EventsError
	switch {
	case errors.As(err, &refused):
		out := &Error{Code: refused.Code, Message: refused.Message}
		if refused.Data != nil {
			out.Data = refused.Data
		}
		return nil, out
	case err != nil:
		return nil, e.rpcError(ctx, req.Method, err, modern)
	}
	return res, nil
}
