package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"slices"
	"strings"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	govapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// Server implements the routes of the agents module that are ported; the
// rest of the strict interface is nil and its routes are not mounted.
type Server struct {
	gen.StrictServerInterface
	svc *service.Service
	ext Extras
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server.
func New(svc *service.Service, e Extras) *Server { return &Server{svc: svc, ext: e} }

// areaInput is the route group's validated input kept in the request context.
func areaInput[T any](ctx context.Context) T {
	v, _ := inputFrom(ctx).area.(T)
	return v
}

func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

// MapError renders the module's errors as Python raises them.
func MapError(err error) (*httpx.Error, bool) {
	var (
		inv      *domain.InvalidError
		archived *domain.ErrAgentArchivedError
		nf       *domain.NotFoundError
		unwired  *service.UnwiredError
		perm     *service.PermissionError
		enforced *govapi.ApprovalEnforcedError
		refused  *govapi.InstallRefusedError
	)
	switch {
	case errors.Is(err, domain.ErrAgentNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Agent not found"), true
	case errors.Is(err, service.ErrDenied):
		return httpx.HTTPError(http.StatusForbidden, "Permission denied"), true
	case errors.As(err, &archived):
		return httpx.HTTPError(http.StatusConflict, archived.Error()), true
	case errors.Is(err, domain.ErrReasoningConflict):
		return httpx.HTTPError(http.StatusUnprocessableEntity, err.Error()), true
	case errors.As(err, &inv):
		if inv.Code == domain.CodeInvalidCodeTools {
			return httpx.HTTPError(http.StatusBadRequest, inv.Detail), true
		}
		return httpx.NewError(http.StatusBadRequest, inv.Code, inv.Detail), true
	case errors.As(err, &nf):
		return httpx.NotFound(nf.Error()), true
	case errors.As(err, &perm):
		return httpx.Forbidden(perm.Error()), true
	case errors.As(err, &unwired):
		return httpx.NewError(http.StatusNotImplemented, "not_implemented", unwired.Error()), true
	case errors.As(err, &enforced):
		targets := slices.Clone(enforced.Targets)
		slices.Sort(targets)
		return httpx.NewError(http.StatusConflict, "approval_enforced_by_policy", enforced.Error()).With("targets", targets), true
	case errors.As(err, &refused):
		return httpx.Forbidden(refused.Error()), true
	}
	return mapOthers(err)
}

func orNil(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func boolNil(b *bool) any {
	if b == nil {
		return nil
	}
	return *b
}

// toolsJSON is AgentResponse.tools: null for no tools, [] for a legacy dict.
func toolsJSON(raw []byte, tools []domain.Tool) any {
	t := strings.TrimSpace(string(raw))
	switch {
	case t == "" || t == "null" || t == "[]":
		return nil
	case strings.HasPrefix(t, "{"):
		if t == "{}" {
			return nil
		}
		return []any{}
	}
	out := make([]any, len(tools))
	for i, tl := range tools {
		out[i] = service.ToolResponse(tl)
	}
	return out
}

func answerCheckJSON(raw []byte) any {
	var v struct {
		Enabled            *bool   `json:"enabled"`
		Language           *string `json:"language"`
		RewriteInstruction *string `json:"rewrite_instruction"`
	}
	if len(raw) == 0 || json.Unmarshal(raw, &v) != nil || string(raw) == "null" || string(raw) == "{}" {
		return nil
	}
	enabled := true
	if v.Enabled != nil {
		enabled = *v.Enabled
	}
	return wirejson.Object{{Key: "enabled", Value: enabled}, {Key: "language", Value: orNil(v.Language)},
		{Key: "rewrite_instruction", Value: orNil(v.RewriteInstruction)}}
}

// agentJSON is AgentResponse in its field order.
func agentJSON(v service.View, withSkills bool) wirejson.Object {
	a := v.Agent
	var client any
	if v.Client != nil {
		client = wirejson.Object{{Key: "id", Value: v.Client.ID}, {Key: "name", Value: v.Client.Name},
			{Key: "kind", Value: v.Client.Kind}, {Key: "online", Value: v.Online}, {Key: "default_model", Value: orNil(v.Client.DefaultModel)}}
	}
	var reasoningTokens any
	if a.ReasoningMaxTokens != nil {
		reasoningTokens = int64(*a.ReasoningMaxTokens)
	}
	var skills any
	if withSkills && len(a.Skills) > 0 {
		arr := make([]any, len(a.Skills))
		for i, s := range a.Skills {
			arr[i] = wirejson.Object{{Key: "id", Value: s.ID}, {Key: "name", Value: s.Name}, {Key: "description", Value: orNil(s.Description)}}
		}
		skills = arr
	}
	return wirejson.Object{
		{Key: "id", Value: a.ID}, {Key: "slug", Value: a.Slug}, {Key: "name", Value: a.Name}, {Key: "status", Value: a.Status},
		{Key: "description", Value: orNil(a.Description)}, {Key: "instruction", Value: orNil(a.Instruction)},
		{Key: "model_id", Value: orNil(a.ModelID)}, {Key: "client_id", Value: orNil(a.ClientID)}, {Key: "client", Value: client},
		{Key: "tools", Value: toolsJSON(a.Tools, v.Tools)}, {Key: "planning", Value: boolNil(a.Planning)},
		{Key: "a2ui_enabled", Value: boolNil(a.A2UIEnabled)}, {Key: "reasoning_effort", Value: orNil(a.ReasoningEffort)},
		{Key: "reasoning_max_tokens", Value: reasoningTokens}, {Key: "answer_check", Value: answerCheckJSON(a.AnswerCheck)},
		{Key: "agent_type", Value: a.AgentType}, {Key: "skills", Value: skills}, {Key: "is_catalog", Value: a.IsCatalog},
		{Key: "registry_item_id", Value: orNil(a.RegistryItemID)}, {Key: "update_available", Value: a.UpdateAvailable},
		{Key: "a2a_url", Value: orNil(v.A2AURL)},
	}
}

func (s *Server) list(ctx context.Context) (gen.ListAgentsV1AgentsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	vs, err := s.svc.List(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(vs))
	for i, v := range vs {
		out[i] = agentJSON(v, false)
	}
	return ok(out), nil
}

func (s *Server) ListAgentsV1AgentsGet(ctx context.Context, _ gen.ListAgentsV1AgentsGetRequestObject) (gen.ListAgentsV1AgentsGetResponseObject, error) {
	return s.list(ctx)
}

func (s *Server) ListAgentsV1AgentsGetDup2(ctx context.Context, _ gen.ListAgentsV1AgentsGetDup2RequestObject) (gen.ListAgentsV1AgentsGetDup2ResponseObject, error) {
	r, err := s.list(ctx)
	if err != nil {
		return nil, err
	}
	return r.(response), nil
}

func (s *Server) CreateAgentV1AgentsPost(ctx context.Context, _ gen.CreateAgentV1AgentsPostRequestObject) (gen.CreateAgentV1AgentsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.Create(ctx, c, inputFrom(ctx).create)
	if err != nil {
		return nil, err
	}
	return ok(agentJSON(v, false)), nil
}

func (s *Server) GetAgentV1AgentsAgentIdGet(ctx context.Context, rq gen.GetAgentV1AgentsAgentIdGetRequestObject) (gen.GetAgentV1AgentsAgentIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.Get(ctx, c, rq.AgentId)
	if err != nil {
		return nil, err
	}
	return ok(agentJSON(v, true)), nil
}

func (s *Server) UpdateAgentV1AgentsAgentIdPatch(ctx context.Context, rq gen.UpdateAgentV1AgentsAgentIdPatchRequestObject) (gen.UpdateAgentV1AgentsAgentIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.Update(ctx, c, rq.AgentId, inputFrom(ctx).patch)
	if err != nil {
		return nil, err
	}
	return ok(agentJSON(v, true)), nil
}

func (s *Server) DeleteAgentV1AgentsAgentIdDelete(ctx context.Context, rq gen.DeleteAgentV1AgentsAgentIdDeleteRequestObject) (gen.DeleteAgentV1AgentsAgentIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.Archive(ctx, c, rq.AgentId); err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "status", Value: "success"}}), nil
}

func (s *Server) RestoreAgentV1AgentsAgentIdRestorePost(ctx context.Context, rq gen.RestoreAgentV1AgentsAgentIdRestorePostRequestObject) (gen.RestoreAgentV1AgentsAgentIdRestorePostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.Restore(ctx, c, rq.AgentId)
	if err != nil {
		return nil, err
	}
	return ok(agentJSON(v, true)), nil
}

var _ = authz.TypeResource
