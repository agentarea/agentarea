package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/wallet"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
)

// Mount registers the wallet routes on r behind workspace, the edge's
// middleware that admits the caller into /v1/workspaces/{workspace}.
func Mount(r chi.Router, errs *httpx.Errors, workspace func(http.Handler) http.Handler, s *Server) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	base := r.With(workspace)
	on := func(rq request) chi.Router { return base.With(rq.middleware(errs)) }
	p := httpx.WorkspacePrefix + "/agents/{agent_id}/wallet"

	on(request{body: createBody}).Post(p, w.CreateWalletV1AgentsAgentIdWalletPost)
	on(request{}).Get(p, w.GetWalletV1AgentsAgentIdWalletGet)
	on(request{body: updateBody}).Put(p, w.UpdateWalletV1AgentsAgentIdWalletPut)
	on(request{}).Delete(p, w.DeleteWalletV1AgentsAgentIdWalletDelete)
	on(request{}).Get(p+"/balance", w.GetWalletBalanceV1AgentsAgentIdWalletBalanceGet)
	on(request{query: paymentsQuery}).Get(p+"/payments", w.GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGet)
	on(request{body: fundBody}).Post(p+"/fund", w.FundWalletV1AgentsAgentIdWalletFundPost)
}
