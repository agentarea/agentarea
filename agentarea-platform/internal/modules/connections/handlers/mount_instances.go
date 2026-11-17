package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
)

// mountInstances routes /mcp-server-instances; a route whose port is nil is
// not mounted. Verify, discover-tools, validate, validate-connection and
// probe are mounted with verification.
func mountInstances(g group) {
	ports := g.s.svc.InstancePorts()
	with := func(rq request, mws ...func(http.Handler) http.Handler) chi.Router {
		return g.base.With(append(mws, rq.middleware(g.errs))...)
	}
	need := func(permission string) func(http.Handler) http.Handler {
		return requires(g.s, g.errs, permission, "mcp_instance", "instance_id")
	}
	p := httpx.WorkspacePrefix + "/mcp-server-instances"
	id := []string{"instance_id"}
	w := g.w

	with(request{}).Get(p+"/", w.ListMcpServerInstancesV1McpServerInstancesGet)
	with(request{pathUUIDs: id}).Get(p+"/{instance_id}", w.GetMcpServerInstanceV1McpServerInstancesInstanceIdGet)
	with(request{pathUUIDs: id, body: instanceUpdateBody}, need("edit")).
		Patch(p+"/{instance_id}", w.UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatch)
	with(request{pathUUIDs: id}, need("delete")).
		Delete(p+"/{instance_id}", w.DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDelete)
	with(request{pathUUIDs: id, body: sharingBody}, need("view")).
		Put(p+"/{instance_id}/sharing", w.SetMcpServerInstanceSharingV1McpServerInstancesInstanceIdSharingPut)
	with(request{pathUUIDs: id}, need("edit")).
		Post(p+"/{instance_id}/test-auth", w.RunTestAuthV1McpServerInstancesInstanceIdTestAuthPost)
	with(request{pathUUIDs: id, body: anyDictBody}, need("edit")).
		Post(p+"/{instance_id}/oauth-link", w.CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPost)
	g.adminOn(request{pathUUIDs: id}).
		Get(p+"/{instance_id}/environment", w.GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGet)
	g.adminOn(request{pathUUIDs: id}).
		Get(p+"/{instance_id}/oauth-links", w.ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGet)

	if ports.Specs {
		with(request{body: instanceCreateBody}).Post(p+"/", w.CreateMcpServerInstanceV1McpServerInstancesPost)
		with(request{body: withSpecBody}).Post(p+"/with-spec", w.CreateMcpServerConnectionV1McpServerInstancesWithSpecPost)
	}
	if ports.Runtime {
		with(request{}).Get(p+"/health/containers", w.GetContainersHealthV1McpServerInstancesHealthContainersGet)
		with(request{body: anyDictBody}).Post(p+"/check", w.CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPost)
	}
	if ports.Consumers {
		with(request{pathUUIDs: id}).
			Get(p+"/{instance_id}/consumers", w.ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGet)
	}
	if ports.Policies {
		with(request{}).Get(p+"/tool-policies", w.ListMcpServerInstanceToolPoliciesV1McpServerInstancesToolPoliciesGet)
		with(request{pathUUIDs: id}).
			Get(p+"/{instance_id}/tool-policies", w.GetMcpServerInstanceToolPoliciesV1McpServerInstancesInstanceIdToolPoliciesGet)
	}
}
