package handlers

import (
	"context"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mcpserve"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpserver"
	streamsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

// mountMCP routes the platform MCP server (/mcp spanning the caller's
// workspaces, /mcp/w/{workspace} pinned to one) and a client's bundle
// (/mcp/clients/{client_id}, legacy /client-mcp/{client_id}).
func mountMCP(g group) {
	if g.e.Gate == nil {
		return
	}
	svc := g.s.svc
	log, apiURL := svc.Log(), svc.APIURL()
	auth := mcpserver.Auth{Gate: g.e.Gate, APIURL: apiURL, Log: log}
	info := mcpserver.Identity(apiURL, mcpserver.PlatformName, mcpserver.PlatformInstructions)
	info.Resources, info.Prompts = true, true

	span := mcpserver.NewPlatform(true, info, auth, log)
	span.Register(g.ports.MCPToolsets...)
	span.UseEvents(g.ports.Events)
	pinned := mcpserver.NewPlatform(false, info, auth, log)
	pinned.Register(g.ports.MCPToolsets...)
	pinned.UseEvents(g.ports.Events)

	mcpHandle(g.r, mcpserve.MountPinned, pinned.Handler(mcpserve.MountPinned))
	if svc.ClientEndpointReady() {
		clients := mcpClientEndpoint(g, pinned)
		mcpHandle(g.r, mcpserve.MountClients+"/{client_id}", clients(mcpserve.MountClients))
		mcpHandle(g.r, mcpserve.MountLegacy+"/{client_id}", clients(mcpserve.MountLegacy))
	}
	mcpHandle(g.r, mcpserve.MountSpan, span.Handler(mcpserve.MountSpan))
}

// handle serves pattern and its trailing-slash form alike, as the mount
// root's own address (no redirect).
func mcpHandle(r chi.Router, pattern string, h http.Handler) {
	r.Handle(pattern, h)
	r.Handle(pattern+"/", h)
}

// clientEndpoint is client_mcp_server behind ClientMCPScopeMiddleware and an
// auth middleware that lets a turn's token in.
func mcpClientEndpoint(g group, platform *mcpserver.Platform) func(prefix string) http.Handler {
	svc := g.s.svc
	info := mcpserver.Identity(svc.APIURL(), "AgentArea Client", "Scoped tool bundle for a registered client (agent-proxy).")
	info.Resources = true
	info.Extensions = map[string]map[string]any{mcpserver.AppsExtension: {}}
	endpoint := &mcpserver.Endpoint{Info: info, Log: svc.Log(), Backend: func(r *http.Request) (mcpserver.Backend, error) {
		p, ok := authn.PrincipalFrom(r.Context())
		if !ok {
			return nil, authn.ErrNoPrincipal
		}
		return svc.ClientEndpoint(r.Context(), p, chi.URLParam(r, "client_id"), g.e.Gate.EnterWorkspace, platform)
	}}
	if ev := g.ports.Events; ev != nil {
		endpoint.Events = &mcpserver.EventsHandler{Server: ev.Server, Scope: func(r *http.Request) (streamsapi.EventsScope, error) {
			p, ok := authn.PrincipalFrom(r.Context())
			if !ok {
				return nil, authn.ErrNoPrincipal
			}
			clientID := chi.URLParam(r, "client_id")
			return mcpserver.ClientEventsScope(func(ctx context.Context) (authn.Caller, bool, error) {
				return svc.ClientCaller(ctx, p, clientID, g.e.Gate.EnterWorkspace)
			}), nil
		}}
	}
	auth := mcpserver.Auth{Gate: g.e.Gate, APIURL: svc.APIURL(), AdmitTurn: true, Log: svc.Log()}
	return func(prefix string) http.Handler {
		resource := strings.Trim(prefix, "/")
		return auth.Wrap(endpoint, func(r *http.Request) mcpserver.Mount {
			return mcpserver.Mount{Resource: resource + "/" + chi.URLParam(r, "client_id")}
		})
	}
}
