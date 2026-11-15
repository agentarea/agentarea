package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
)

// A2A permissions (A2APermissions).
const (
	A2APermRead    = "agent:read"
	A2APermExecute = "agent:execute"
)

// ErrA2AAgentNotFound is load_a2a_agent's 404 "Agent not found".
var ErrA2AAgentNotFound = errors.New("a2a agent not found")

// ErrA2AAuthRequired is require_a2a_auth's 401 for an anonymous caller.
var ErrA2AAuthRequired = errors.New("authentication required")

// A2AForbiddenError is require_a2a_auth's 403 for a caller the policy refuses.
type A2AForbiddenError struct{ Permission string }

func (e *A2AForbiddenError) Error() string {
	return "Insufficient permissions. Required: " + e.Permission
}

// A2ACardAgentNotFoundError is a discovery route's 404 "Agent {id} not found".
type A2ACardAgentNotFoundError struct{ ID string }

func (e *A2ACardAgentNotFoundError) Error() string { return "Agent " + e.ID + " not found" }

// A2ADocumentError is a discovery document's 500 with its own detail.
type A2ADocumentError struct {
	Detail string
	Err    error
}

func (e *A2ADocumentError) Error() string { return e.Detail }

func (e *A2ADocumentError) Unwrap() error { return e.Err }

// A2A serves the A2A surface.
type A2A struct {
	s     *Service
	d     A2APorts
	tasks A2ATasks
}

// NewA2A builds the service over the agents service.
func NewA2A(s *Service, d A2APorts) *A2A {
	a := &A2A{s: s, d: d, tasks: d.Tasks}
	if a.tasks == nil && d.Runs != nil {
		a.tasks = &a2aTasks{a: a}
	}
	return a
}

// Agent is get_public_agent: the agent by id in any workspace, archived included.
func (a *A2A) Agent(ctx context.Context, id uuid.UUID) (domain.Agent, bool, error) {
	q, release, err := a.s.d.DB.Global().Read(ctx)
	if err != nil {
		return domain.Agent{}, false, err
	}
	defer release()
	return store.A2AAgent(ctx, q, id)
}

func (a *A2A) discovered(ctx context.Context, id uuid.UUID) (domain.Agent, error) {
	agent, ok, err := a.Agent(ctx, id)
	if err != nil {
		return domain.Agent{}, err
	}
	if !ok {
		return domain.Agent{}, &A2ACardAgentNotFoundError{ID: id.String()}
	}
	return agent, nil
}

// APIRPCURL is agent_rpc_url.
func (a *A2A) APIRPCURL(id uuid.UUID) string { return domain.A2AAPIRPCURL(a.d.APIURL, id.String()) }

// HostRPCURL is agent_host_rpc_url.
func (a *A2A) HostRPCURL(id uuid.UUID) string { return domain.A2AHostRPCURL(a.d.AgentURL, id.String()) }

// HostAgent is the agent id an agent host's Host header names.
func (a *A2A) HostAgent(host string) (string, bool) { return domain.A2AHostAgent(a.d.AgentURL, host) }

// PublicCard is public_agent_card_response: the card whose endpoint is rpcURL.
func (a *A2A) PublicCard(ctx context.Context, id uuid.UUID, rpcURL string) (domain.A2AJSON, error) {
	agent, err := a.discovered(ctx, id)
	if err != nil {
		return nil, err
	}
	a.info(ctx, "Agent well-known discovery", "agent_name", agent.Name, "agent_id", agent.ID)
	return domain.A2ACard(agent, rpcURL, false), nil
}

func (a *A2A) document(ctx context.Context, id uuid.UUID, detail string, build func(domain.Agent) domain.A2AJSON) (domain.A2AJSON, error) {
	agent, err := a.discovered(ctx, id)
	var missing *A2ACardAgentNotFoundError
	if errors.As(err, &missing) {
		return nil, err
	}
	if err != nil {
		a.error(ctx, detail, "agent_id", id.String(), "error", err.Error())
		return nil, &A2ADocumentError{Detail: detail, Err: err}
	}
	return build(agent), nil
}

// Info is get_agent_a2a_info.
func (a *A2A) Info(ctx context.Context, id uuid.UUID) (domain.A2AJSON, error) {
	return a.document(ctx, id, "A2A info failed", func(ag domain.Agent) domain.A2AJSON {
		return domain.A2AInfo(ag, a.d.APIURL, a.d.AgentURL)
	})
}

// Index is get_agent_well_known_index.
func (a *A2A) Index(ctx context.Context, id uuid.UUID) (domain.A2AJSON, error) {
	return a.document(ctx, id, "Well-known index failed", func(ag domain.Agent) domain.A2AJSON {
		return domain.A2AWellKnownIndex(ag, a.d.APIURL, a.d.AgentURL)
	})
}

// A2ARequestMeta is what the request says about the caller (_a2a_metadata).
type A2ARequestMeta struct {
	// UserAgent is nil when the request had no User-Agent.
	UserAgent *string
	ClientIP  string
}

// A2AAdmission is a caller admitted to an agent: the agent, the principal
// (nil for anonymous) and the A2AAuthContext.
type A2AAdmission struct {
	Agent     domain.Agent
	Principal *authn.Principal
	Auth      domain.A2AAuth
}

// Principal is get_optional_principal: nil without a bearer token or for one the gate refuses.
func (a *A2A) Principal(ctx context.Context, token string) (*authn.Principal, error) {
	if token == "" {
		return nil, nil
	}
	if a.d.Principal == nil {
		return nil, &UnwiredError{Feature: "A2A authentication"}
	}
	return a.d.Principal(ctx, token)
}

// a2aAllowed is authorize_agent_action: no public grants exist; an agent's
// key reaches its own agent only; anyone else reaches the agents of the
// workspaces they can access.
func a2aAllowed(p *authn.Principal, agent domain.Agent) bool {
	if p == nil {
		return false
	}
	if p.BoundAgentID != "" {
		return p.BoundAgentID == agent.ID && p.BoundWorkspaceID == agent.WorkspaceID
	}
	return slices.Contains(p.AccessibleWorkspaces, agent.WorkspaceID)
}

// Admit is require_a2a_auth after load_a2a_agent: the agent rawID names, the
// caller token authenticates, and whether permission is theirs on it.
func (a *A2A) Admit(ctx context.Context, rawID, token, permission string, meta A2ARequestMeta) (A2AAdmission, error) {
	id, err := uuid.Parse(rawID)
	if err != nil {
		return A2AAdmission{}, ErrA2AAgentNotFound
	}
	agent, ok, err := a.Agent(ctx, id)
	if err != nil {
		return A2AAdmission{}, err
	}
	if !ok {
		return A2AAdmission{}, ErrA2AAgentNotFound
	}
	p, err := a.Principal(ctx, token)
	if err != nil {
		return A2AAdmission{}, err
	}
	if !a2aAllowed(p, agent) {
		if p == nil {
			return A2AAdmission{}, ErrA2AAuthRequired
		}
		a.warn(ctx, "A2A authorization denied", "user_id", p.UserID, "agent_id", agent.ID, "required", permission)
		return A2AAdmission{}, &A2AForbiddenError{Permission: permission}
	}
	md := domain.A2AJSON{{Key: "user_agent", Value: nil}, {Key: "client_ip", Value: nil}}
	if meta.UserAgent != nil {
		md.Set("user_agent", *meta.UserAgent)
	}
	if meta.ClientIP != "" {
		md.Set("client_ip", meta.ClientIP)
	}
	md = append(md, domain.A2AMember{Key: "agent_name", Value: agent.Name}, domain.A2AMember{Key: "agent_status", Value: agent.Status})
	auth := domain.A2AAuth{
		Authenticated: p != nil, WorkspaceID: agent.WorkspaceID, AgentID: agent.ID,
		Permissions: []string{permission}, AuthMethod: "anonymous", Metadata: md,
	}
	if p != nil {
		auth.UserID, auth.AuthMethod = p.UserID, "bearer"
		if p.BoundAgentID != "" && p.Credential != nil {
			auth.AgentKeyID = p.Credential.KeyID
		}
	}
	return A2AAdmission{Agent: agent, Principal: p, Auth: auth}, nil
}

// Limit is limit_a2a_rpc's bucket for identity; without a limiter every call passes.
func (a *A2A) Limit(ctx context.Context, identity string) error {
	if a.d.RateLimiter == nil {
		return nil
	}
	return httpx.EnforceRateLimit(ctx, a.d.RateLimiter, a.d.Log, httpx.A2ARPCScope, identity, httpx.A2ARPCLimit)
}

func a2aAvailable(status string) bool {
	switch strings.ToLower(status) {
	case "active", "available", "ready":
		return true
	}
	return false
}

// precheck is the dispatcher's method, params and version checks.
func (a *A2A) precheck(req domain.A2ARPCRequest, version string) domain.A2AJSON {
	if !domain.A2AKnownMethod(req.Method) {
		return domain.A2ARPCFailure(req.ID, domain.A2AMethodNotFound())
	}
	if e := domain.A2AParseParams(req.Method, req.Params, req.HasParams); e != nil {
		return domain.A2ARPCFailure(req.ID, e)
	}
	if e := domain.A2ACheckVersion(version); e != nil {
		return domain.A2ARPCFailure(req.ID, e)
	}
	return nil
}

// IsStreaming reports whether method answers as an event stream.
func (a *A2A) IsStreaming(method string) bool {
	return method == "SendStreamingMessage" || method == "SubscribeToTask"
}

// Dispatch is JsonRpcDispatcher.handle_requests after framing: the method,
// its params, the A2A-Version header, then the handler; the JSON-RPC response.
// An *httpx.Error a handler raised (a refused permission) is returned as the
// HTTP answer, as the dispatcher re-raises an HTTPException.
func (a *A2A) Dispatch(ctx context.Context, adm A2AAdmission, rpcURL string, req domain.A2ARPCRequest, version string) (domain.A2AJSON, error) {
	if failure := a.precheck(req, version); failure != nil {
		return failure, nil
	}
	result, err := a.call(ctx, adm, rpcURL, req)
	if err != nil {
		rpc, herr := a.failure(ctx, req, err)
		if herr != nil {
			return nil, herr
		}
		return domain.A2ARPCFailure(req.ID, rpc), nil
	}
	return domain.A2ARPCResult(req.ID, result), nil
}

// failure is the JSON-RPC error of a handler error, or the HTTP error to pass on.
func (a *A2A) failure(ctx context.Context, req domain.A2ARPCRequest, err error) (*domain.A2ARPCError, error) {
	var rpc *domain.A2ARPCError
	if errors.As(err, &rpc) {
		return rpc, nil
	}
	var he *httpx.Error
	if errors.As(err, &he) {
		return nil, err
	}
	a.error(ctx, "A2A call raised an unexpected error", "method", req.Method, "error", err.Error())
	return domain.A2AInternal("Internal error"), nil
}

// DispatchStream serves a streaming method. emit gets each JSON-RPC response;
// failed marks an error frame. A body returned is the plain JSON answer of a
// call that failed before its first event; an error is the HTTP answer.
func (a *A2A) DispatchStream(ctx context.Context, adm A2AAdmission, rpcURL string, req domain.A2ARPCRequest, version string, emit func(body domain.A2AJSON, failed bool) error) (domain.A2AJSON, error) {
	if failure := a.precheck(req, version); failure != nil {
		return failure, nil
	}
	if a.tasks == nil {
		return domain.A2ARPCFailure(req.ID, domain.A2AUnavailable(req.Method)), nil
	}
	call, err := a.taskCall(adm, rpcURL, req)
	if err != nil {
		rpc, herr := a.failure(ctx, req, err)
		if herr != nil {
			return nil, herr
		}
		return domain.A2ARPCFailure(req.ID, rpc), nil
	}
	emitted := false
	err = a.tasks.Stream(ctx, call, func(ev domain.A2AJSON) error {
		emitted = true
		return emit(domain.A2ARPCResult(req.ID, ev), false)
	})
	if err == nil {
		return nil, nil
	}
	rpc, herr := a.failure(ctx, req, err)
	if herr != nil && !emitted {
		return nil, herr
	}
	if herr != nil {
		rpc = domain.A2AInternal("Internal error")
	}
	if !emitted {
		return domain.A2ARPCFailure(req.ID, rpc), nil
	}
	return nil, emit(domain.A2ARPCFailure(req.ID, rpc), true)
}

func (a *A2A) taskCall(adm A2AAdmission, rpcURL string, req domain.A2ARPCRequest) (A2ACall, error) {
	caller, err := a2aCaller(adm)
	if err != nil {
		return A2ACall{}, err
	}
	id, _ := uuid.Parse(adm.Agent.ID)
	return A2ACall{
		Method: req.Method, Params: req.Params, RequestID: req.ID, AgentID: id, RPCURL: rpcURL, Auth: adm.Auth, Caller: caller,
	}, nil
}

func (a *A2A) call(ctx context.Context, adm A2AAdmission, rpcURL string, req domain.A2ARPCRequest) (any, error) {
	if req.Method == "GetExtendedAgentCard" {
		return a.extendedCard(ctx, adm, rpcURL)
	}
	if a.tasks == nil || a.IsStreaming(req.Method) {
		return nil, domain.A2AUnavailable(req.Method)
	}
	call, err := a.taskCall(adm, rpcURL, req)
	if err != nil {
		return nil, err
	}
	result, err := a.tasks.Handle(ctx, call)
	if err != nil || result == nil {
		return nil, err
	}
	return result, nil
}

// a2aCaller is _user_context: the caller acting in the agent's workspace; an
// agent's key reaches that workspace only and administers nothing. Only an
// agent's key is a credential here: a personal key is its user.
func a2aCaller(adm A2AAdmission) (authn.Caller, error) {
	auth := adm.Auth
	if !auth.Authenticated || auth.UserID == "" || auth.WorkspaceID == "" || adm.Principal == nil {
		return authn.Caller{}, domain.A2AInvalidRequest("A2A requests require an authenticated user")
	}
	ws, err := scope.NewWorkspace(auth.WorkspaceID, "")
	if err != nil {
		return authn.Caller{}, err
	}
	p := *adm.Principal
	p.Credential = nil
	if auth.AgentKeyID != "" {
		p.AccessibleWorkspaces, p.AdminWorkspaces = []string{auth.WorkspaceID}, []string{}
		p.Credential = &authn.Credential{Kind: authn.KindAPIKey, KeyID: auth.AgentKeyID}
	}
	return p.Enter(ws)
}

// extendedCard is on_get_extended_agent_card.
func (a *A2A) extendedCard(ctx context.Context, adm A2AAdmission, rpcURL string) (domain.A2AJSON, error) {
	if _, err := a2aCaller(adm); err != nil {
		return nil, err
	}
	ws, err := scope.NewWorkspace(adm.Auth.WorkspaceID, "")
	if err != nil {
		return nil, err
	}
	id, _ := uuid.Parse(adm.Agent.ID)
	var agent domain.Agent
	var found bool
	err = a.s.read(ctx, ws, func(sess db.Session) error {
		var err error
		agent, found, err = a.s.store.Get(ctx, sess, id)
		return err
	})
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, domain.A2AInvalidParams(fmt.Sprintf("Agent with ID %s does not exist", id))
	}
	if agent.Status != "" && !a2aAvailable(agent.Status) {
		return nil, domain.A2AInvalidParams(fmt.Sprintf("Agent %s (ID: %s) is not available (status: %s)", agent.Name, id, agent.Status))
	}
	return domain.A2ACard(agent, rpcURL, true), nil
}

// A2AFromWire is a wirejson value as the domain reads it.
func A2AFromWire(v any) any {
	switch x := v.(type) {
	case wirejson.Object:
		out := make(domain.A2AJSON, len(x))
		for i, m := range x {
			out[i] = domain.A2AMember{Key: m.Key, Value: A2AFromWire(m.Value)}
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = A2AFromWire(e)
		}
		return out
	case wirejson.Float:
		return float64(x)
	}
	return v
}

// A2AToWire is a domain value as wirejson writes it: a float64 is a Python float.
func A2AToWire(v any) any {
	switch x := v.(type) {
	case domain.A2AJSON:
		out := make(wirejson.Object, len(x))
		for i, m := range x {
			out[i] = wirejson.Member{Key: m.Key, Value: A2AToWire(m.Value)}
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = A2AToWire(e)
		}
		return out
	case float64:
		return wirejson.Float(x)
	case json.Number:
		return x
	}
	return v
}

func (a *A2A) info(ctx context.Context, msg string, args ...any) {
	if a.d.Log != nil {
		a.d.Log.InfoContext(ctx, msg, args...)
	}
}

func (a *A2A) warn(ctx context.Context, msg string, args ...any) {
	if a.d.Log != nil {
		a.d.Log.WarnContext(ctx, msg, args...)
	}
}

func (a *A2A) error(ctx context.Context, msg string, args ...any) {
	if a.d.Log != nil {
		a.d.Log.ErrorContext(ctx, msg, args...)
	}
}
