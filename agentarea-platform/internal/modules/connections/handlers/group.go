package handlers

import (
	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/connections"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
)

// group is what each route group's mount reads: the router, the edge, the
// generated wrapper and the workspace-admitted base.
type group struct {
	r       chi.Router
	errs    *httpx.Errors
	e       Edge
	s       *Server
	w       *gen.ServerInterfaceWrapper
	base    chi.Router
	adminOn func(rq request) chi.Router
	ports   Ports
}
