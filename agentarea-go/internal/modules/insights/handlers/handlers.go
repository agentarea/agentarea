// Package handlers of insights: HTTP handlers, one file per Python router file; errors.go maps typed errors to problems.
package handlers

import (
	"context"
	"errors"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/insights"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/service"
)

// Server implements the insights routes. GET /health is the serve edge's
// root route, and PUT /settings is mounted as putSettings, which tells an
// absent body from a null one; both come from unported and are never mounted.
type Server struct {
	unported
	svc *service.Service
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server.
func New(svc *service.Service) *Server { return &Server{svc: svc} }

// MapError renders the module's errors as Python raises them.
func MapError(err error) (*httpx.Error, bool) {
	var refused *governanceapi.CapRefused
	switch {
	case errors.Is(err, service.ErrBalanceUnavailable):
		return httpx.HTTPError(http.StatusServiceUnavailable, "balance is unavailable"), true
	case errors.Is(err, service.ErrAgentNotFound):
		return httpx.HTTPError(http.StatusNotFound, service.ErrAgentNotFound.Error()), true
	case errors.Is(err, service.ErrMembershipGraphDown):
		return httpx.HTTPError(http.StatusServiceUnavailable, service.ErrMembershipGraphDown.Error()), true
	case errors.As(err, &refused):
		return httpx.HTTPError(http.StatusUnprocessableEntity, refused.Detail), true
	}
	return nil, false
}

// response is a JSON body as Starlette writes it.
type response struct {
	status int
	raw    []byte
}

func (x response) visit(w http.ResponseWriter) error {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(x.raw)))
	w.WriteHeader(x.status)
	_, err := w.Write(x.raw)
	return err
}

func (x response) VisitGetAnalyticsV1AnalyticsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetBalanceV1BalanceGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetDashboardV1DashboardGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetAgentOverviewV1AgentsAgentIdOverviewGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetWorkspaceSettingsV1SettingsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetNetworkTopologyV1NetworkTopologyGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetNetworkPeopleAccessV1NetworkPeopleAccessGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func jsonBody(status int, body any) (response, error) {
	raw, err := wirejson.Marshal(body, wirejson.Compact)
	if err != nil {
		return response{}, err
	}
	return response{status: status, raw: raw}, nil
}

func (s *Server) GetAnalyticsV1AnalyticsGet(ctx context.Context, _ gen.GetAnalyticsV1AnalyticsGetRequestObject) (gen.GetAnalyticsV1AnalyticsGetResponseObject, error) {
	a, err := s.svc.Analytics(ctx)
	if err != nil {
		return nil, err
	}
	return jsonBody(http.StatusOK, wirejson.Object{
		{Key: "enabled", Value: a.Enabled},
		{Key: "install_id", Value: a.InstallID},
		{Key: "collector_url", Value: a.CollectorURL},
		{Key: "edition", Value: a.Edition},
	})
}

func (s *Server) GetBalanceV1BalanceGet(ctx context.Context, _ gen.GetBalanceV1BalanceGetRequestObject) (gen.GetBalanceV1BalanceGetResponseObject, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return nil, authn.ErrWorkspaceNotSelected
	}
	b, err := s.svc.Balance(ctx, c)
	if err != nil {
		return nil, err
	}
	if b == nil {
		return response{status: http.StatusOK, raw: []byte("null")}, nil
	}
	return jsonBody(http.StatusOK, balanceJSON(*b))
}

// balanceJSON is BalanceResponse in its field order.
func balanceJSON(b domain.Balance) wirejson.Object {
	return wirejson.Object{
		{Key: "currency", Value: b.Currency},
		{Key: "exhausted", Value: b.Exhausted},
		{Key: "viewer_is_payer", Value: b.ViewerIsPayer},
		{Key: "amount", Value: b.Amount},
		{Key: "spend_per_day", Value: b.SpendPerDay},
		{Key: "runway_days", Value: b.RunwayDays},
	}
}

func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

func (s *Server) GetDashboardV1DashboardGet(ctx context.Context, _ gen.GetDashboardV1DashboardGetRequestObject) (gen.GetDashboardV1DashboardGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	d, err := s.svc.Dashboard(ctx, c)
	if err != nil {
		return nil, err
	}
	return jsonBody(http.StatusOK, dashboardJSON(d))
}

func (s *Server) GetAgentOverviewV1AgentsAgentIdOverviewGet(ctx context.Context, req gen.GetAgentOverviewV1AgentsAgentIdOverviewGetRequestObject) (gen.GetAgentOverviewV1AgentsAgentIdOverviewGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	o, err := s.svc.Overview(ctx, c, req.AgentId.String())
	if err != nil {
		return nil, err
	}
	return jsonBody(http.StatusOK, overviewJSON(o))
}

func (s *Server) GetWorkspaceSettingsV1SettingsGet(ctx context.Context, _ gen.GetWorkspaceSettingsV1SettingsGetRequestObject) (gen.GetWorkspaceSettingsV1SettingsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	capUSD, err := s.svc.Settings(ctx, c)
	if err != nil {
		return nil, err
	}
	return jsonBody(http.StatusOK, settingsJSON(capUSD))
}

func (s *Server) GetNetworkTopologyV1NetworkTopologyGet(ctx context.Context, _ gen.GetNetworkTopologyV1NetworkTopologyGetRequestObject) (gen.GetNetworkTopologyV1NetworkTopologyGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	t, err := s.svc.Topology(ctx, c)
	if err != nil {
		return nil, err
	}
	return jsonBody(http.StatusOK, topologyJSON(t))
}

func (s *Server) GetNetworkPeopleAccessV1NetworkPeopleAccessGet(ctx context.Context, _ gen.GetNetworkPeopleAccessV1NetworkPeopleAccessGetRequestObject) (gen.GetNetworkPeopleAccessV1NetworkPeopleAccessGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	p, err := s.svc.PeopleAccess(ctx, c)
	if err != nil {
		return nil, err
	}
	return jsonBody(http.StatusOK, peopleJSON(p))
}

// putSettings is PUT /settings: the admin check runs before the body is
// read, as requires_workspace_admin does; monthly_cap_usd is required and
// null removes the cap.
func (s *Server) putSettings(w http.ResponseWriter, r *http.Request) error {
	ctx := r.Context()
	c, err := caller(ctx)
	if err != nil {
		return err
	}
	if err := s.svc.RequireAdmin(ctx); err != nil {
		return err
	}
	v, err := readBody(r)
	if err != nil {
		return err
	}
	amount, err := settingsBody(v)
	if err != nil {
		return err
	}
	if err := s.svc.SetSettings(ctx, c, amount); err != nil {
		return err
	}
	out, err := jsonBody(http.StatusOK, settingsJSON(amount))
	if err != nil {
		return err
	}
	return out.visit(w)
}

// settingsBody is WorkspaceSettingsUpdate: monthly_cap_usd: Money | None = Field(ge=0).
func settingsBody(v any) (*money.Decimal, error) {
	var errs []httpx.FieldError
	o, ok := model(v, []any{"body"}, &errs)
	if !ok {
		return nil, httpx.Validation(errs...)
	}
	loc := []any{"body", "monthly_cap_usd"}
	raw, present := o.Get("monthly_cap_usd")
	if !present {
		return nil, httpx.Validation(httpx.Missing(loc...))
	}
	if raw == nil {
		return nil, nil
	}
	var c governanceapi.Checker
	d, ok := c.Money(raw, loc, false)
	if !ok {
		return nil, httpx.Validation(c.Errs...)
	}
	return &d, nil
}

// pathUUID refuses a path parameter that is not a UUID as pydantic does (422).
func pathUUID(errs *httpx.Errors, name string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if _, fe := httpx.ValidateUUID(chi.URLParam(r, name), "path", name); fe != nil {
				errs.Write(w, r, httpx.Validation(*fe))
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// Mount registers GET /v1/analytics behind principal and the workspace
// routes (balance, dashboard, agent overview, settings, network) behind
// workspace.
func Mount(r chi.Router, errs *httpx.Errors, workspace, principal func(http.Handler) http.Handler, s *Server) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	r.With(principal).Get("/v1/analytics", w.GetAnalyticsV1AnalyticsGet)
	ws := r.With(workspace)
	p := httpx.WorkspacePrefix
	ws.Get(p+"/balance", w.GetBalanceV1BalanceGet)
	ws.Get(p+"/dashboard", w.GetDashboardV1DashboardGet)
	ws.With(pathUUID(errs, "agent_id")).Get(p+"/agents/{agent_id}/overview", w.GetAgentOverviewV1AgentsAgentIdOverviewGet)
	ws.Get(p+"/settings", w.GetWorkspaceSettingsV1SettingsGet)
	ws.Method(http.MethodPut, p+"/settings", errs.Handler(s.putSettings))
	ws.Get(p+"/network/topology", w.GetNetworkTopologyV1NetworkTopologyGet)
	ws.Get(p+"/network/people-access", w.GetNetworkPeopleAccessV1NetworkPeopleAccessGet)
}
