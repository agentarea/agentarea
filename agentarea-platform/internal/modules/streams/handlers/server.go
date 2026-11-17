// Package handlers implements the streams routes that are ported (api/v1/triggers.py).
package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/streams"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
)

// Server implements the ported streams routes. Operations not ported are
// never mounted, so the embedded interface is never called for them.
type Server struct {
	gen.StrictServerInterface
	svc  *service.Service
	rate httpx.RateLimiter
	log  *slog.Logger
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server.
func New(svc *service.Service, rate httpx.RateLimiter, log *slog.Logger) *Server {
	if log == nil {
		log = slog.Default()
	}
	return &Server{svc: svc, rate: rate, log: log}
}

func triggerJSON(t domain.Trigger) gen.TriggerResponse {
	id, _ := uuid.Parse(t.ID)
	agent, _ := uuid.Parse(t.AgentID)
	out := gen.TriggerResponse{
		Id: id, AgentId: agent, Name: t.Name, Description: t.Description, TriggerType: t.Type,
		IsActive: t.IsActive, TaskParameters: t.TaskParameters, Conditions: t.Conditions,
		FailureThreshold: t.FailureThreshold, ConsecutiveFailures: t.Consecutive,
		CreatedAt: t.CreatedAt, UpdatedAt: t.UpdatedAt, CreatedBy: t.CreatedBy,
		LastExecutionAt: t.LastExecutionAt, NeedsNewOwnerAt: t.NeedsNewOwnerAt,
		Status: gen.TriggerResponseStatus(t.Status()), CronExpression: t.CronExpression, Timezone: t.Timezone,
	}
	if t.TaskDefinitionID != nil {
		td, _ := uuid.Parse(*t.TaskDefinitionID)
		out.TaskDefinitionId = &td
	}
	if t.Type == domain.TypeStream {
		out.Session = session(t.Session)
		out.Batch = batch(t.Batch)
	}
	if t.Binding != nil {
		sid, _ := uuid.Parse(t.Binding.StreamID)
		out.StreamId = &sid
		f := map[string]interface{}(t.Binding.Filter)
		out.EventFilter = &f
		out.LastEventAt = t.Binding.LastEventAt
	}
	return out
}

func session(s *domain.Session) *gen.TriggerSession {
	if s == nil {
		return nil
	}
	return &gen.TriggerSession{Continue: s.Continue, IdleTimeout: s.IdleTimeout}
}

func batch(b *domain.Batch) *gen.TriggerBatchWindow {
	if b == nil {
		return nil
	}
	return &gen.TriggerBatchWindow{MaxEvents: b.MaxEvents, Window: b.Window}
}

// caller is the workspace caller the edge resolved.
func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

func notFound(id string, err error) error {
	if errors.Is(err, domain.ErrNotFound) {
		return httpx.NotFound(fmt.Sprintf("Trigger %s not found", id))
	}
	return err
}

func (s *Server) ListTriggersV1TriggersGet(ctx context.Context, req gen.ListTriggersV1TriggersGetRequestObject) (gen.ListTriggersV1TriggersGetResponseObject, error) {
	if _, err := caller(ctx); err != nil {
		return nil, err
	}
	f := store.Filter{ActiveOnly: req.Params.ActiveOnly != nil && *req.Params.ActiveOnly, Limit: 100}
	if req.Params.Limit != nil {
		if *req.Params.Limit < 1 || *req.Params.Limit > 1000 {
			return nil, httpx.HTTPError(http.StatusUnprocessableEntity, "limit must be between 1 and 1000")
		}
		f.Limit = int32(*req.Params.Limit)
	}
	if req.Params.AgentId != nil {
		a := req.Params.AgentId.String()
		f.AgentID = &a
	}
	if req.Params.TriggerType != nil {
		tt := string(*req.Params.TriggerType)
		f.TriggerType = &tt
	}
	ts, err := s.svc.List(ctx, f)
	if err != nil {
		return nil, err
	}
	out := make(gen.ListTriggersV1TriggersGet200JSONResponse, 0, len(ts))
	for _, t := range ts {
		out = append(out, triggerJSON(t))
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) CreateTriggerV1TriggersPost(ctx context.Context, req gen.CreateTriggerV1TriggersPostRequestObject) (gen.CreateTriggerV1TriggersPostResponseObject, error) {
	if req.Body == nil {
		return nil, httpx.BadRequest("request body is required")
	}
	b := req.Body
	n := domain.NewTrigger{
		Name: b.Name, AgentID: b.AgentId.String(), Type: string(b.TriggerType),
		EventFilter: deref(b.EventFilter), TaskParameters: deref(b.TaskParameters), Conditions: deref(b.Conditions),
		FailureThreshold: 5, CronExpression: b.CronExpression, Timezone: b.Timezone, Enabled: true,
	}
	if b.Description != nil {
		n.Description = *b.Description
	}
	if b.Enabled != nil {
		n.Enabled = *b.Enabled
	}
	if b.FailureThreshold != nil {
		n.FailureThreshold = *b.FailureThreshold
	}
	if b.StreamId != nil {
		sid := b.StreamId.String()
		n.StreamID = &sid
	}
	if b.TaskDefinitionId != nil {
		td := b.TaskDefinitionId.String()
		n.TaskDefinitionID = &td
	}
	if b.Session != nil {
		n.Session = &domain.Session{Continue: b.Session.Continue, IdleTimeout: b.Session.IdleTimeout}
	}
	if b.Batch != nil {
		n.Batch = &domain.Batch{MaxEvents: b.Batch.MaxEvents, Window: b.Batch.Window}
	}
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if c.UserID == "" {
		return nil, httpx.BadRequest("User ID is required to create a trigger")
	}
	t, err := s.svc.Create(ctx, n)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: triggerJSON(t)}, nil
}

func (s *Server) GetTriggerV1TriggersTriggerIdGet(ctx context.Context, req gen.GetTriggerV1TriggersTriggerIdGetRequestObject) (gen.GetTriggerV1TriggersTriggerIdGetResponseObject, error) {
	id := req.TriggerId.String()
	t, err := s.svc.Get(ctx, id)
	if err != nil {
		return nil, notFound(id, err)
	}
	return response{status: http.StatusOK, body: triggerJSON(t)}, nil
}

func (s *Server) UpdateTriggerV1TriggersTriggerIdPut(ctx context.Context, req gen.UpdateTriggerV1TriggersTriggerIdPutRequestObject) (gen.UpdateTriggerV1TriggersTriggerIdPutResponseObject, error) {
	if req.Body == nil {
		return nil, httpx.BadRequest("request body is required")
	}
	id := req.TriggerId.String()
	b := req.Body
	p := service.Patch{
		Name: b.Name, Description: b.Description, Enabled: b.Enabled, CronExpression: b.CronExpression,
		Timezone: b.Timezone, FailureThreshold: b.FailureThreshold,
	}
	if b.AgentId != nil {
		a := b.AgentId.String()
		p.AgentID = &a
	}
	sent, _ := ctx.Value(presenceKey{}).(presence)
	if b.TaskDefinitionId != nil {
		td := b.TaskDefinitionId.String()
		p.TaskDefinitionID = &td
	}
	p.TaskDefinitionSet = b.TaskDefinitionId != nil || sent.null["task_definition_id"]
	if b.Conditions != nil {
		p.Conditions = *b.Conditions
	}
	if b.TaskParameters != nil {
		p.TaskParameters = *b.TaskParameters
	}
	if b.EventFilter != nil {
		p.EventFilter = *b.EventFilter
	}
	if b.Session != nil {
		p.Session = &domain.Session{Continue: b.Session.Continue, IdleTimeout: b.Session.IdleTimeout}
	}
	p.SessionSet = b.Session != nil || sent.null["session"]
	if b.Batch != nil {
		p.Batch = &domain.Batch{MaxEvents: b.Batch.MaxEvents, Window: b.Batch.Window}
	}
	p.BatchSet = b.Batch != nil || sent.null["batch"]
	if p.Enabled == nil {
		p.Enabled = sent.isActive
	}
	t, err := s.svc.Update(ctx, id, p)
	if err != nil {
		return nil, notFound(id, err)
	}
	return response{status: http.StatusOK, body: triggerJSON(t)}, nil
}

type presenceKey struct{}

// presence is what a TriggerUpdate body sent that its decoded struct cannot tell: the
// keys sent as null (null clears task_definition_id, session and batch; absent keeps
// them) and the is_active alias of enabled.
type presence struct {
	null     map[string]bool
	isActive *bool
}

// updatePresence reads the PUT body once for presence, then hands it on unchanged.
func updatePresence(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, err := io.ReadAll(r.Body)
		if err != nil {
			httpx.WriteProblem(w, httpx.Problem{Status: http.StatusBadRequest, Code: httpx.CodeBadRequest, Title: httpx.Title(http.StatusBadRequest), Detail: "could not read the request body"}, nil)
			return
		}
		r.Body = io.NopCloser(bytes.NewReader(raw))
		var fields map[string]json.RawMessage
		if json.Unmarshal(raw, &fields) == nil {
			p := presence{null: map[string]bool{}}
			for k, v := range fields {
				if string(bytes.TrimSpace(v)) == "null" {
					p.null[k] = true
				}
			}
			var active bool
			if v, ok := fields["is_active"]; ok && json.Unmarshal(v, &active) == nil {
				p.isActive = &active
			}
			r = r.WithContext(context.WithValue(r.Context(), presenceKey{}, p))
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) DeleteTriggerV1TriggersTriggerIdDelete(ctx context.Context, req gen.DeleteTriggerV1TriggersTriggerIdDeleteRequestObject) (gen.DeleteTriggerV1TriggersTriggerIdDeleteResponseObject, error) {
	id := req.TriggerId.String()
	if err := s.svc.Delete(ctx, id); err != nil {
		return nil, notFound(id, err)
	}
	return response{status: http.StatusNoContent}, nil
}

func (s *Server) EnableTriggerV1TriggersTriggerIdEnablePost(ctx context.Context, req gen.EnableTriggerV1TriggersTriggerIdEnablePostRequestObject) (gen.EnableTriggerV1TriggersTriggerIdEnablePostResponseObject, error) {
	id := req.TriggerId.String()
	if _, err := s.svc.Enable(ctx, id); err != nil {
		return nil, notFound(id, err)
	}
	return response{status: http.StatusOK, body: toggled("enabled", id, true)}, nil
}

func (s *Server) DisableTriggerV1TriggersTriggerIdDisablePost(ctx context.Context, req gen.DisableTriggerV1TriggersTriggerIdDisablePostRequestObject) (gen.DisableTriggerV1TriggersTriggerIdDisablePostResponseObject, error) {
	id := req.TriggerId.String()
	if _, err := s.svc.Disable(ctx, id); err != nil {
		return nil, notFound(id, err)
	}
	return response{status: http.StatusOK, body: toggled("disabled", id, false)}, nil
}

func toggled(verb, id string, active bool) map[string]any {
	return map[string]any{"status": "success", "message": fmt.Sprintf("Trigger %s %s successfully", id, verb),
		"trigger_id": id, "is_active": active}
}

func deref[T any](p *T) T {
	var zero T
	if p == nil {
		return zero
	}
	return *p
}

// response is one of the ported routes' answers; the status and body are what the Python route returns.
type response struct {
	status int
	body   any
}

func (x response) write(w http.ResponseWriter) error {
	if x.status == http.StatusNoContent {
		w.WriteHeader(x.status)
		return nil
	}
	raw, err := json.Marshal(x.body)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(x.status)
	_, err = w.Write(raw)
	return err
}

func (x response) VisitListTriggersV1TriggersGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitCreateTriggerV1TriggersPostResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitGetTriggerV1TriggersTriggerIdGetResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitUpdateTriggerV1TriggersTriggerIdPutResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitDeleteTriggerV1TriggersTriggerIdDeleteResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitEnableTriggerV1TriggersTriggerIdEnablePostResponse(w http.ResponseWriter) error {
	return x.write(w)
}
func (x response) VisitDisableTriggerV1TriggersTriggerIdDisablePostResponse(w http.ResponseWriter) error {
	return x.write(w)
}
