// Package handlers implements the connections routes that are ported: the
// auth configs, the OAuth links and the OpenAPI connections' reads and delete.
package handlers

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/connections"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// Server implements the ported operations of the generated strict interface.
// The embedded interface supplies the rest (the other operations of the
// connections tag): they are never routed, see Mount, so a call to one would
// be a wiring bug.
type Server struct {
	gen.StrictServerInterface
	svc  *service.Service
	rate httpx.RateLimiter
	log  *slog.Logger
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server.
func New(svc *service.Service) *Server { return &Server{svc: svc} }

// WithRateLimit is the limiter anonymous client registration takes its token from.
func (s *Server) WithRateLimit(rl httpx.RateLimiter, log *slog.Logger) *Server {
	s.rate, s.log = rl, log
	return s
}

// caller is the workspace caller the edge resolved; a route mounted without
// the workspace middleware is a wiring bug.
func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

// uuidOf is the path or body UUID, already validated by the middleware.
func uuidOf(s string) uuid.UUID { return uuid.MustParse(s) }

func (s *Server) ListConnectionsV1OpenapiConnectionsGet(ctx context.Context, _ gen.ListConnectionsV1OpenapiConnectionsGetRequestObject) (gen.ListConnectionsV1OpenapiConnectionsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	views, err := s.svc.ListConnections(ctx, c, service.ConnectionFilter{Status: in.status, Pattern: in.pattern}, in.limit, in.offset)
	if err != nil {
		return nil, err
	}
	out := make([]any, 0, len(views))
	for _, v := range views {
		out = append(out, connectionJSON(v))
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) GetConnectionV1OpenapiConnectionsConnectionIdGet(ctx context.Context, rq gen.GetConnectionV1OpenapiConnectionsConnectionIdGetRequestObject) (gen.GetConnectionV1OpenapiConnectionsConnectionIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.GetConnection(ctx, c, uuidOf(rq.ConnectionId.String()))
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: connectionJSON(v)}, nil
}

func (s *Server) DeleteConnectionV1OpenapiConnectionsConnectionIdDelete(ctx context.Context, rq gen.DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteRequestObject) (gen.DeleteConnectionV1OpenapiConnectionsConnectionIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.DeleteConnection(ctx, c, uuidOf(rq.ConnectionId.String())); err != nil {
		return nil, err
	}
	return response{status: http.StatusNoContent}, nil
}

func (s *Server) ListMcpAuthConfigsV1McpAuthConfigsGet(ctx context.Context, _ gen.ListMcpAuthConfigsV1McpAuthConfigsGetRequestObject) (gen.ListMcpAuthConfigsV1McpAuthConfigsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := s.svc.ListAuthConfigs(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]any, 0, len(rows))
	for _, a := range rows {
		out = append(out, authJSON(a))
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) CreateMcpAuthConfigV1McpAuthConfigsPost(ctx context.Context, _ gen.CreateMcpAuthConfigV1McpAuthConfigsPostRequestObject) (gen.CreateMcpAuthConfigV1McpAuthConfigsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	a, err := s.svc.CreateAuthConfig(ctx, c, inputFrom(ctx).auth)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: authJSON(a)}, nil
}

func (s *Server) GetMcpAuthConfigV1McpAuthConfigsConfigIdGet(ctx context.Context, rq gen.GetMcpAuthConfigV1McpAuthConfigsConfigIdGetRequestObject) (gen.GetMcpAuthConfigV1McpAuthConfigsConfigIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	a, err := s.svc.GetAuthConfig(ctx, c, uuidOf(rq.ConfigId.String()))
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: authJSON(a)}, nil
}

func (s *Server) UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPut(ctx context.Context, rq gen.UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutRequestObject) (gen.UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	a, err := s.svc.UpdateAuthConfig(ctx, c, uuidOf(rq.ConfigId.String()), inputFrom(ctx).patch)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: authJSON(a)}, nil
}

func (s *Server) DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDelete(ctx context.Context, rq gen.DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteRequestObject) (gen.DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.DeleteAuthConfig(ctx, c, uuidOf(rq.ConfigId.String())); err != nil {
		return nil, err
	}
	return response{status: http.StatusNoContent}, nil
}

func (s *Server) CreateOauthLinkV1McpOauthLinksPost(ctx context.Context, _ gen.CreateOauthLinkV1McpOauthLinksPostRequestObject) (gen.CreateOauthLinkV1McpOauthLinksPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx).link
	l, err := s.svc.CreateLink(ctx, c, in.instance, in.access, in.provider, in.days)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: linkJSON(l)}, nil
}

func (s *Server) ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGet(ctx context.Context, rq gen.ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetRequestObject) (gen.ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := s.svc.ListLinks(ctx, c, uuidOf(rq.InstanceId.String()))
	if err != nil {
		return nil, err
	}
	out := make([]any, 0, len(rows))
	for _, l := range rows {
		out = append(out, linkJSON(l))
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) GetOauthLinkV1McpOauthLinksLinkIdGet(ctx context.Context, rq gen.GetOauthLinkV1McpOauthLinksLinkIdGetRequestObject) (gen.GetOauthLinkV1McpOauthLinksLinkIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	l, err := s.svc.GetLink(ctx, c, uuidOf(rq.LinkId.String()))
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: linkJSON(l)}, nil
}

func (s *Server) RevokeOauthLinkV1McpOauthLinksLinkIdDelete(ctx context.Context, rq gen.RevokeOauthLinkV1McpOauthLinksLinkIdDeleteRequestObject) (gen.RevokeOauthLinkV1McpOauthLinksLinkIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.RevokeLink(ctx, c, uuidOf(rq.LinkId.String())); err != nil {
		return nil, err
	}
	return response{status: http.StatusNoContent}, nil
}
