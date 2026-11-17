package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/streams"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
)

// Mount registers the streams, triggers and webhook routes on r. Workspace
// routes sit behind workspace, the edge's middleware that admits the caller
// into /v1/workspaces/{workspace}; the webhook sink sits at the root. A route
// whose port is not wired is not registered.
func Mount(r chi.Router, errs *httpx.Errors, workspace func(http.Handler) http.Handler, s *Server) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	base := r.With(workspace)
	mountTriggers(base, w)
	mountTriggerReads(base, w)
	mountTriggerFiring(base, w, s)
	mountStreams(base, w, s, errs)
	mountSources(base, w, s)
	mountWebhooks(r, w, s, errs)
}

func mountTriggers(base chi.Router, w *gen.ServerInterfaceWrapper) {
	p := httpx.WorkspacePrefix + "/triggers"
	base.Get(p+"/", w.ListTriggersV1TriggersGet)
	base.Post(p+"/", w.CreateTriggerV1TriggersPost)
	base.Get(p+"/{trigger_id}", w.GetTriggerV1TriggersTriggerIdGet)
	base.With(updatePresence).Put(p+"/{trigger_id}", w.UpdateTriggerV1TriggersTriggerIdPut)
	base.Delete(p+"/{trigger_id}", w.DeleteTriggerV1TriggersTriggerIdDelete)
	base.Post(p+"/{trigger_id}/enable", w.EnableTriggerV1TriggersTriggerIdEnablePost)
	base.Post(p+"/{trigger_id}/disable", w.DisableTriggerV1TriggersTriggerIdDisablePost)
}
