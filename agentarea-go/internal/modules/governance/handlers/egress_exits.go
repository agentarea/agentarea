package handlers

import (
	"context"
	"net/http"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/governance"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
)

// egressGate is the router dependency _deployment_has_egress_exits: the
// open-core edition has no egress_exits extension, so every route is a 404
// before its parameters are read.
func egressGate(errs *httpx.Errors) func(http.Handler) http.Handler {
	return func(http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			errs.Write(w, r, egressUnavailable())
		})
	}
}

func egressUnavailable() error { return httpx.HTTPError(http.StatusNotFound, EgressDetail) }

func (s *Server) ListEgressExitsV1EgressExitsGet(context.Context, gen.ListEgressExitsV1EgressExitsGetRequestObject) (gen.ListEgressExitsV1EgressExitsGetResponseObject, error) {
	return nil, egressUnavailable()
}

func (s *Server) CreateEgressExitV1EgressExitsPost(context.Context, gen.CreateEgressExitV1EgressExitsPostRequestObject) (gen.CreateEgressExitV1EgressExitsPostResponseObject, error) {
	return nil, egressUnavailable()
}

func (s *Server) GetEgressExitV1EgressExitsExitIdGet(context.Context, gen.GetEgressExitV1EgressExitsExitIdGetRequestObject) (gen.GetEgressExitV1EgressExitsExitIdGetResponseObject, error) {
	return nil, egressUnavailable()
}

func (s *Server) UpdateEgressExitV1EgressExitsExitIdPatch(context.Context, gen.UpdateEgressExitV1EgressExitsExitIdPatchRequestObject) (gen.UpdateEgressExitV1EgressExitsExitIdPatchResponseObject, error) {
	return nil, egressUnavailable()
}

func (s *Server) DeleteEgressExitV1EgressExitsExitIdDelete(context.Context, gen.DeleteEgressExitV1EgressExitsExitIdDeleteRequestObject) (gen.DeleteEgressExitV1EgressExitsExitIdDeleteResponseObject, error) {
	return nil, egressUnavailable()
}
