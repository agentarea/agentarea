package handlers

import (
	"context"
	"net/http"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/governance"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
)

// Routes says which optional route groups have their ports.
type Routes struct {
	Secrets   bool
	Snapshots bool
}

// Mount registers the governance routes on r behind workspace, the edge's
// middleware that admits the caller into /v1/workspaces/{workspace}.
func Mount(r chi.Router, errs *httpx.Errors, workspace func(http.Handler) http.Handler, admin func(context.Context) error, s *Server, on Routes) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	base := r.With(workspace)
	route := func(rq request) chi.Router { return base.With(rq.middleware(errs, admin)) }
	ws := httpx.WorkspacePrefix

	p := ws + "/policies"
	rule := []string{"rule_id"}
	route(request{admin: true, query: ruleListQuery}).Get(p, w.ListPolicyRulesV1PoliciesGet)
	route(request{body: ruleCreateBody}).Post(p, w.CreatePolicyRuleV1PoliciesPost)
	route(request{admin: true, pathUUIDs: rule}).Get(p+"/{rule_id}", w.GetPolicyRuleV1PoliciesRuleIdGet)
	route(request{pathUUIDs: rule, body: ruleUpdateBody}).Patch(p+"/{rule_id}", w.UpdatePolicyRuleV1PoliciesRuleIdPatch)
	route(request{pathUUIDs: rule}).Delete(p+"/{rule_id}", w.DeletePolicyRuleV1PoliciesRuleIdDelete)

	g := ws + "/governance"
	route(request{body: previewBody}).Post(g+"/effective-policy/preview", w.PreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPost)
	if on.Snapshots {
		route(request{pathUUIDs: []string{"task_id"}}).Get(g+"/task-policy-snapshots/{task_id}", w.GetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGet)
	}

	route(request{admin: true, query: auditQuery}).Get(ws+"/audit-logs/", w.ListAuditLogsV1AuditLogsGet)

	e := ws + "/egress-exits"
	gate := base.With(egressGate(errs))
	gate.Get(e+"/", w.ListEgressExitsV1EgressExitsGet)
	gate.Post(e+"/", w.CreateEgressExitV1EgressExitsPost)
	gate.Get(e+"/{exit_id}", w.GetEgressExitV1EgressExitsExitIdGet)
	gate.Patch(e+"/{exit_id}", w.UpdateEgressExitV1EgressExitsExitIdPatch)
	gate.Delete(e+"/{exit_id}", w.DeleteEgressExitV1EgressExitsExitIdDelete)

	if !on.Secrets {
		return
	}
	sp := ws + "/secrets"
	secret := []string{"secret_id"}
	route(request{}).Get(sp, w.ListSecretsV1SecretsGet)
	route(request{admin: true, body: secretCreateBody}).Post(sp, w.CreateSecretV1SecretsPost)
	route(request{pathUUIDs: secret}).Get(sp+"/{secret_id}", w.GetSecretV1SecretsSecretIdGet)
	route(request{admin: true, pathUUIDs: secret, body: secretDescriptionBody}).Patch(sp+"/{secret_id}", w.UpdateSecretDescriptionV1SecretsSecretIdPatch)
	route(request{admin: true, pathUUIDs: secret, body: secretValueBody}).Put(sp+"/{secret_id}/value", w.RotateSecretV1SecretsSecretIdValuePut)
	route(request{admin: true, pathUUIDs: secret}).Delete(sp+"/{secret_id}", w.DeleteSecretV1SecretsSecretIdDelete)
}
