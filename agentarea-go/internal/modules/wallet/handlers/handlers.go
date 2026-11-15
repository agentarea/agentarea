package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/wallet"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/service"
)

// Server implements the wallet routes (api/v1/wallet.py).
type Server struct {
	svc   *service.Service
	admin func(ctx context.Context) error
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server; admin is assert_workspace_admin for the caller in ctx.
func New(svc *service.Service, admin func(ctx context.Context) error) *Server {
	return &Server{svc: svc, admin: admin}
}

// MapError renders the module's errors as Python raises them.
func MapError(err error) (*httpx.Error, bool) {
	var cfg *domain.ConfigError
	switch {
	case errors.Is(err, api.ErrNotFound):
		return httpx.HTTPError(http.StatusNotFound, "No wallet configured for this agent"), true
	case errors.Is(err, domain.ErrAgentNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Agent not found"), true
	case errors.Is(err, domain.ErrAlreadyExists):
		return httpx.HTTPError(http.StatusConflict, "Wallet already exists for this agent"), true
	case errors.As(err, &cfg):
		return httpx.HTTPError(http.StatusBadRequest, cfg.Message), true
	}
	return nil, false
}

func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

// target is who is acting on which agent's wallet.
type target struct {
	ws     scope.Workspace
	userID string
	agent  uuid.UUID
	in     input
}

// reading is a GET route: the admin check is a route dependency and runs
// before the agent is resolved; the query is reported last.
func (s *Server) reading(ctx context.Context, agentID string) (target, error) {
	c, err := caller(ctx)
	if err != nil {
		return target{}, err
	}
	if err := s.admin(ctx); err != nil {
		return target{}, err
	}
	return s.resolved(ctx, c, agentID)
}

// writing is a mutation: the agent is resolved (404) and the body validated
// (422) before the handler asserts the caller administers the workspace.
func (s *Server) writing(ctx context.Context, agentID string) (target, error) {
	c, err := caller(ctx)
	if err != nil {
		return target{}, err
	}
	t, err := s.resolved(ctx, c, agentID)
	if err != nil {
		return target{}, err
	}
	if err := s.admin(ctx); err != nil {
		return target{}, err
	}
	return t, nil
}

// deleting is a mutation without a body.
func (s *Server) deleting(ctx context.Context, agentID string) (target, error) {
	return s.writing(ctx, agentID)
}

func (s *Server) resolved(ctx context.Context, c authn.Caller, agentID string) (target, error) {
	id, err := s.svc.ResolveAgent(ctx, c.Workspace, agentID)
	if err != nil {
		return target{}, err
	}
	in := inputFrom(ctx)
	if err := httpx.Validation(in.errs...); err != nil {
		return target{}, err
	}
	return target{ws: c.Workspace, userID: c.UserID, agent: id, in: in}, nil
}

// response is a JSONResponse body as Starlette writes it, or an empty 204.
type response struct {
	status int
	body   any
}

func (x response) visit(w http.ResponseWriter) error {
	if x.status == http.StatusNoContent {
		w.WriteHeader(x.status)
		return nil
	}
	raw, err := wirejson.Marshal(x.body, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(x.status)
	_, err = w.Write(raw)
	return err
}

func (x response) VisitDeleteWalletV1AgentsAgentIdWalletDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetWalletV1AgentsAgentIdWalletGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateWalletV1AgentsAgentIdWalletPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateWalletV1AgentsAgentIdWalletPutResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetWalletBalanceV1AgentsAgentIdWalletBalanceGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitFundWalletV1AgentsAgentIdWalletFundPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

// utcISO is utc_isoformat of a naive UTC timestamp: isoformat() with a Z.
func utcISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond() == 0 {
		return t.Format("2006-01-02T15:04:05") + "Z"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "Z"
}

// jsonValue is a stored JSON column as the parsed value (key order kept), nil when none.
func jsonValue(raw json.RawMessage) any {
	if len(raw) == 0 {
		return nil
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil
	}
	return v
}

// walletJSON is WalletResponse in its field order.
func walletJSON(w api.Wallet) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: w.ID},
		{Key: "agent_id", Value: w.AgentID},
		{Key: "wallet_type", Value: w.Type},
		{Key: "x402_config", Value: jsonValue(w.X402Config)},
		{Key: "mpp_config", Value: jsonValue(w.MPPConfig)},
		{Key: "has_credentials", Value: w.CredentialsRef != nil},
		{Key: "service_budget_usd", Value: w.Budget.String()},
		{Key: "service_budget_period", Value: w.Period},
		{Key: "status", Value: w.Status},
		{Key: "created_at", Value: utcISO(w.CreatedAt)},
		{Key: "updated_at", Value: utcISO(w.UpdatedAt)},
	}
}

// paymentJSON is PaymentRecordResponse in its field order.
func paymentJSON(p api.Payment) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: p.ID},
		{Key: "agent_id", Value: p.AgentID},
		{Key: "execution_id", Value: p.ExecutionID},
		{Key: "protocol", Value: p.Protocol},
		{Key: "amount_usd", Value: p.Amount.String()},
		{Key: "recipient", Value: p.Recipient},
		{Key: "tx_hash", Value: p.TxHash},
		{Key: "tool_name", Value: p.ToolName},
		{Key: "tool_call_id", Value: p.ToolCallID},
		{Key: "status", Value: p.Status},
		{Key: "error_message", Value: p.ErrorMessage},
		{Key: "protocol_metadata", Value: jsonValue(p.ProtocolMetadata)},
		{Key: "created_at", Value: utcISO(p.CreatedAt)},
	}
}

func (s *Server) CreateWalletV1AgentsAgentIdWalletPost(ctx context.Context, rq gen.CreateWalletV1AgentsAgentIdWalletPostRequestObject) (gen.CreateWalletV1AgentsAgentIdWalletPostResponseObject, error) {
	t, err := s.writing(ctx, rq.AgentId)
	if err != nil {
		return nil, err
	}
	w, err := s.svc.Create(ctx, t.ws, t.userID, t.agent, t.in.create)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: walletJSON(w)}, nil
}

func (s *Server) GetWalletV1AgentsAgentIdWalletGet(ctx context.Context, rq gen.GetWalletV1AgentsAgentIdWalletGetRequestObject) (gen.GetWalletV1AgentsAgentIdWalletGetResponseObject, error) {
	t, err := s.reading(ctx, rq.AgentId)
	if err != nil {
		return nil, err
	}
	w, err := s.svc.Get(ctx, t.ws, t.agent)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: walletJSON(w)}, nil
}

func (s *Server) UpdateWalletV1AgentsAgentIdWalletPut(ctx context.Context, rq gen.UpdateWalletV1AgentsAgentIdWalletPutRequestObject) (gen.UpdateWalletV1AgentsAgentIdWalletPutResponseObject, error) {
	t, err := s.writing(ctx, rq.AgentId)
	if err != nil {
		return nil, err
	}
	w, err := s.svc.Update(ctx, t.ws, t.userID, t.agent, t.in.update)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: walletJSON(w)}, nil
}

func (s *Server) DeleteWalletV1AgentsAgentIdWalletDelete(ctx context.Context, rq gen.DeleteWalletV1AgentsAgentIdWalletDeleteRequestObject) (gen.DeleteWalletV1AgentsAgentIdWalletDeleteResponseObject, error) {
	t, err := s.deleting(ctx, rq.AgentId)
	if err != nil {
		return nil, err
	}
	if err := s.svc.Delete(ctx, t.ws, t.userID, t.agent); err != nil {
		return nil, err
	}
	return response{status: http.StatusNoContent}, nil
}

func (s *Server) GetWalletBalanceV1AgentsAgentIdWalletBalanceGet(ctx context.Context, rq gen.GetWalletBalanceV1AgentsAgentIdWalletBalanceGetRequestObject) (gen.GetWalletBalanceV1AgentsAgentIdWalletBalanceGetResponseObject, error) {
	t, err := s.reading(ctx, rq.AgentId)
	if err != nil {
		return nil, err
	}
	b, err := s.svc.Balance(ctx, t.ws, t.agent.String())
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: wirejson.Object{
		{Key: "service_budget_usd", Value: b.Budget.String()},
		{Key: "service_budget_period", Value: b.Period},
		{Key: "total_spent_current_period", Value: b.Spent.String()},
		{Key: "remaining", Value: b.Remaining.String()},
	}}, nil
}

func (s *Server) FundWalletV1AgentsAgentIdWalletFundPost(ctx context.Context, rq gen.FundWalletV1AgentsAgentIdWalletFundPostRequestObject) (gen.FundWalletV1AgentsAgentIdWalletFundPostResponseObject, error) {
	t, err := s.writing(ctx, rq.AgentId)
	if err != nil {
		return nil, err
	}
	budget := t.in.fund
	w, err := s.svc.Update(ctx, t.ws, t.userID, t.agent, service.Update{Budget: &budget})
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: walletJSON(w)}, nil
}

func (s *Server) GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGet(ctx context.Context, rq gen.GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetRequestObject) (gen.GetPaymentHistoryV1AgentsAgentIdWalletPaymentsGetResponseObject, error) {
	t, err := s.reading(ctx, rq.AgentId)
	if err != nil {
		return nil, err
	}
	in := t.in
	page, err := s.svc.Payments(ctx, t.ws, t.agent, in.filter, int32(in.size), int32((in.page-1)*in.size))
	if err != nil {
		return nil, err
	}
	items := make([]any, len(page.Items))
	for i, p := range page.Items {
		items[i] = paymentJSON(p)
	}
	return response{status: http.StatusOK, body: wirejson.Object{
		{Key: "items", Value: items}, {Key: "total", Value: page.Total},
		{Key: "page", Value: in.page}, {Key: "page_size", Value: in.size},
	}}, nil
}
