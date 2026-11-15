package handlers

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/connections"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

// instanceError maps the instance routes' errors: MCPValidationError is 422
// with its errors listed, an unfinished runtime retirement 409 or 503 to retry.
func instanceError(err error) (*httpx.Error, bool) {
	var si *domain.SpecInvalid
	var rr *service.RuntimeRetirementError
	switch {
	case errors.As(err, &si):
		list := make([]any, len(si.Errors))
		for i, e := range si.Errors {
			list[i] = e
		}
		return httpx.HTTPError(http.StatusUnprocessableEntity, strings.Join(si.Errors, "; ")).With("errors", list), true
	case errors.As(err, &rr):
		status := http.StatusServiceUnavailable
		if rr.Conflict {
			status = http.StatusConflict
		}
		return httpx.HTTPError(status, rr.Msg).WithHeader("Retry-After", "1"), true
	}
	return nil, false
}

func anyOrNil(m map[string]any) any {
	if m == nil {
		return nil
	}
	return m
}

// instanceJSON is MCPServerInstanceResponse in its field order.
func instanceJSON(v service.InstanceView) wirejson.Object {
	i := v.Instance
	var verification any = i.VerificationRaw
	if v.Verification != nil {
		verification = *v.Verification
	} else if i.VerificationRaw == nil {
		verification = domain.DefaultVerification()
	}
	var tools any
	if i.ToolsSet {
		tools = i.Tools
	}
	return wirejson.Object{
		{Key: "id", Value: i.ID},
		{Key: "name", Value: i.Name},
		{Key: "description", Value: orNil(i.Description)},
		{Key: "server_spec_id", Value: i.ServerSpecID},
		{Key: "transport", Value: i.Transport},
		{Key: "json_spec", Value: domain.MaskedSpec(i.JSONSpec, v.SecretNames)},
		{Key: "verification", Value: verification},
		{Key: "last_dispatch", Value: anyOrNil(i.LastDispatch)},
		{Key: "tools", Value: tools},
		{Key: "events", Value: anyOrNil(i.Events)},
		{Key: "auth_config_id", Value: orNil(i.AuthConfigID)},
		{Key: "managed_by", Value: orNil(i.ManagedBy)},
		{Key: "cost", Value: anyOrNil(i.Cost)},
		{Key: "personal", Value: v.Sharing.Personal},
		{Key: "is_owner", Value: v.Sharing.IsOwner},
		{Key: "created_at", Value: utcISO(i.CreatedAt)},
		{Key: "updated_at", Value: utcISO(i.UpdatedAt)},
	}
}

func instanceToolPoliciesJSON(ps []service.ToolPolicy) []any {
	out := make([]any, 0, len(ps))
	for _, p := range ps {
		out = append(out, wirejson.Object{{Key: "name", Value: p.Name}, {Key: "default", Value: p.Default},
			{Key: "effective", Value: p.Effective}, {Key: "reason", Value: orNil(p.Reason)}})
	}
	return out
}

func stringsOrNil(l []string) any {
	if l == nil {
		return nil
	}
	return l
}

func (s *Server) ListMcpServerInstancesV1McpServerInstancesGet(ctx context.Context, _ gen.ListMcpServerInstancesV1McpServerInstancesGetRequestObject) (gen.ListMcpServerInstancesV1McpServerInstancesGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	views, err := s.svc.ListInstances(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]any, 0, len(views))
	for _, v := range views {
		out = append(out, instanceJSON(v))
	}
	return response{status: http.StatusOK, body: out}, nil
}

// created is 201, or 202 for a container instance still verifying.
func created(v service.InstanceView) response {
	status := http.StatusCreated
	if domain.IsContainer(v.Instance.Transport) {
		status = http.StatusAccepted
	}
	return response{status: status, body: instanceJSON(v)}
}

func (s *Server) CreateMcpServerInstanceV1McpServerInstancesPost(ctx context.Context, _ gen.CreateMcpServerInstanceV1McpServerInstancesPostRequestObject) (gen.CreateMcpServerInstanceV1McpServerInstancesPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.CreateInstance(ctx, c, inputFrom(ctx).instance.create)
	if err != nil {
		return nil, err
	}
	return created(v), nil
}

func (s *Server) CreateMcpServerConnectionV1McpServerInstancesWithSpecPost(ctx context.Context, _ gen.CreateMcpServerConnectionV1McpServerInstancesWithSpecPostRequestObject) (gen.CreateMcpServerConnectionV1McpServerInstancesWithSpecPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx).instance
	if err := withSpecInstanceError(in.create); err != nil {
		return nil, err
	}
	in.create.Name = strings.TrimSpace(in.create.Name)
	v, err := s.svc.CreateInstanceWithSpec(ctx, c, in.server, in.create)
	if err != nil {
		return nil, err
	}
	return created(v), nil
}

func (s *Server) GetMcpServerInstanceV1McpServerInstancesInstanceIdGet(ctx context.Context, rq gen.GetMcpServerInstanceV1McpServerInstancesInstanceIdGetRequestObject) (gen.GetMcpServerInstanceV1McpServerInstancesInstanceIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.InstanceViewOf(ctx, c, uuidOf(rq.InstanceId.String()), true)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: instanceJSON(v)}, nil
}

func (s *Server) UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatch(ctx context.Context, rq gen.UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchRequestObject) (gen.UpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.UpdateInstance(ctx, c, uuidOf(rq.InstanceId.String()), inputFrom(ctx).instance.patch)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: instanceJSON(v)}, nil
}

func (s *Server) DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDelete(ctx context.Context, rq gen.DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDeleteRequestObject) (gen.DeleteMcpServerInstanceV1McpServerInstancesInstanceIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.DeleteInstance(ctx, c, uuidOf(rq.InstanceId.String())); err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: wirejson.Object{{Key: "status", Value: "success"}}}, nil
}

func (s *Server) SetMcpServerInstanceSharingV1McpServerInstancesInstanceIdSharingPut(ctx context.Context, rq gen.SetMcpServerInstanceSharingV1McpServerInstancesInstanceIdSharingPutRequestObject) (gen.SetMcpServerInstanceSharingV1McpServerInstancesInstanceIdSharingPutResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.SetInstanceSharing(ctx, c, uuidOf(rq.InstanceId.String()), inputFrom(ctx).instance.shared)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: instanceJSON(v)}, nil
}

func (s *Server) ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGet(ctx context.Context, rq gen.ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetRequestObject) (gen.ListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := s.svc.Consumers(ctx, c, uuidOf(rq.InstanceId.String()))
	if err != nil {
		return nil, err
	}
	out := make([]any, 0, len(rows))
	for _, r := range rows {
		var slug any
		if r.AgentSlug != "" {
			slug = r.AgentSlug
		}
		out = append(out, wirejson.Object{
			{Key: "agent_id", Value: r.AgentID},
			{Key: "agent_name", Value: r.AgentName},
			{Key: "agent_slug", Value: slug},
			{Key: "enabled_tools", Value: stringsOrNil(r.EnabledTools)},
			{Key: "confirm_tools", Value: r.ConfirmTools},
		})
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) ListMcpServerInstanceToolPoliciesV1McpServerInstancesToolPoliciesGet(ctx context.Context, _ gen.ListMcpServerInstanceToolPoliciesV1McpServerInstancesToolPoliciesGetRequestObject) (gen.ListMcpServerInstanceToolPoliciesV1McpServerInstancesToolPoliciesGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := s.svc.WorkspaceToolPolicies(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]any, 0, len(rows))
	for _, r := range rows {
		out = append(out, wirejson.Object{{Key: "instance_id", Value: r.InstanceID}, {Key: "tools", Value: instanceToolPoliciesJSON(r.Tools)}})
	}
	return response{status: http.StatusOK, body: wirejson.Object{{Key: "instances", Value: out}}}, nil
}

func (s *Server) GetMcpServerInstanceToolPoliciesV1McpServerInstancesInstanceIdToolPoliciesGet(ctx context.Context, rq gen.GetMcpServerInstanceToolPoliciesV1McpServerInstancesInstanceIdToolPoliciesGetRequestObject) (gen.GetMcpServerInstanceToolPoliciesV1McpServerInstancesInstanceIdToolPoliciesGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	ps, err := s.svc.InstanceToolPolicies(ctx, c, uuidOf(rq.InstanceId.String()))
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: wirejson.Object{{Key: "tools", Value: instanceToolPoliciesJSON(ps)}}}, nil
}

func (s *Server) GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGet(ctx context.Context, rq gen.GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGetRequestObject) (gen.GetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	id := rq.InstanceId.String()
	names, err := s.svc.InstanceEnvironment(ctx, c, uuidOf(id))
	if err != nil {
		return nil, httpx.HTTPError(http.StatusInternalServerError, "Internal server error").Wrap(err)
	}
	return response{status: http.StatusOK, body: wirejson.Object{
		{Key: "instance_id", Value: id},
		{Key: "env_vars", Value: names},
		{Key: "message", Value: "Instance has " + strconv.Itoa(len(names)) + " environment variables configured"},
	}}, nil
}

func (s *Server) GetContainersHealthV1McpServerInstancesHealthContainersGet(ctx context.Context, _ gen.GetContainersHealthV1McpServerInstancesHealthContainersGetRequestObject) (gen.GetContainersHealthV1McpServerInstancesHealthContainersGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := s.svc.ContainersHealth(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]any, 0, len(rows))
	healthy := 0
	for _, r := range rows {
		if r.Healthy {
			healthy++
		}
		out = append(out, wirejson.Object{{Key: "instance_id", Value: r.InstanceID}, {Key: "name", Value: r.Name},
			{Key: "healthy", Value: r.Healthy}, {Key: "status", Value: r.Status}})
	}
	return response{status: http.StatusOK, body: wirejson.Object{
		{Key: "instances", Value: out}, {Key: "total", Value: len(rows)}, {Key: "healthy", Value: healthy},
	}}, nil
}

func (s *Server) CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPost(ctx context.Context, _ gen.CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPostRequestObject) (gen.CheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPostResponseObject, error) {
	r, err := s.svc.CheckConfiguration(ctx, inputFrom(ctx).instance.check)
	if err != nil {
		return nil, err
	}
	if r.Valid {
		return response{status: http.StatusOK, body: wirejson.Object{{Key: "valid", Value: true},
			{Key: "message", Value: r.Message}, {Key: "details", Value: anyOrNil(r.Details)}}}, nil
	}
	return response{status: http.StatusOK, body: wirejson.Object{{Key: "valid", Value: false},
		{Key: "message", Value: r.Message}, {Key: "status_code", Value: http.StatusBadRequest}}}, nil
}

func (s *Server) RunTestAuthV1McpServerInstancesInstanceIdTestAuthPost(ctx context.Context, rq gen.RunTestAuthV1McpServerInstancesInstanceIdTestAuthPostRequestObject) (gen.RunTestAuthV1McpServerInstancesInstanceIdTestAuthPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	inst, err := s.svc.GetInstance(ctx, c, uuidOf(rq.InstanceId.String()))
	if err != nil {
		return nil, err
	}
	if inst.AuthConfigID == nil || *inst.AuthConfigID == "" {
		return nil, httpx.HTTPError(http.StatusBadRequest, "No auth config attached to this MCP instance")
	}
	return response{status: http.StatusOK, body: wirejson.Object{
		{Key: "status", Value: "pending"},
		{Key: "message", Value: "Auth test queued. Use /health/containers to verify connectivity once running."},
		{Key: "instance_id", Value: inst.ID},
		{Key: "auth_config_id", Value: *inst.AuthConfigID},
	}}, nil
}

func (s *Server) CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPost(ctx context.Context, rq gen.CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPostRequestObject) (gen.CreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if _, err := s.svc.GetInstance(ctx, c, uuidOf(rq.InstanceId.String())); err != nil {
		return nil, err
	}
	return nil, httpx.HTTPError(http.StatusNotImplemented, "Use the /v1/mcp-oauth-links endpoint to create OAuth links")
}

func (s *Server) ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGet(ctx context.Context, rq gen.ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGetRequestObject) (gen.ListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	id := uuidOf(rq.InstanceId.String())
	if _, err := s.svc.GetInstance(ctx, c, id); err != nil {
		return nil, err
	}
	rows, err := s.svc.ListLinks(ctx, c, id)
	if err != nil {
		return nil, err
	}
	out := make([]any, 0, len(rows))
	for _, l := range rows {
		out = append(out, linkJSON(l))
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (x response) VisitListMcpServerInstancesV1McpServerInstancesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateMcpServerInstanceV1McpServerInstancesPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateMcpServerConnectionV1McpServerInstancesWithSpecPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetMcpServerInstanceV1McpServerInstancesInstanceIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateMcpServerInstanceV1McpServerInstancesInstanceIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteMcpServerInstanceV1McpServerInstancesInstanceIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitSetMcpServerInstanceSharingV1McpServerInstancesInstanceIdSharingPutResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListMcpServerInstanceToolPoliciesV1McpServerInstancesToolPoliciesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetMcpServerInstanceToolPoliciesV1McpServerInstancesInstanceIdToolPoliciesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetContainersHealthV1McpServerInstancesHealthContainersGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCheckMcpServerInstanceConfigurationV1McpServerInstancesCheckPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRunTestAuthV1McpServerInstancesInstanceIdTestAuthPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateOauthLinkV1McpServerInstancesInstanceIdOauthLinkPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListOauthLinksV1McpServerInstancesInstanceIdOauthLinksGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
