package handlers

import (
	"context"
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/streams"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

// mountTriggerFiring registers run and execute when the task port is wired.
func mountTriggerFiring(base chi.Router, w *gen.ServerInterfaceWrapper, s *Server) {
	if !s.svc.CanFire() {
		return
	}
	p := httpx.WorkspacePrefix + "/triggers/{trigger_id}"
	base.Post(p+"/execute", w.ExecuteTriggerV1TriggersTriggerIdExecutePost)
	base.Post(p+"/run", w.RunTriggerNowV1TriggersTriggerIdRunPost)
}

func (x response) VisitExecuteTriggerV1TriggersTriggerIdExecutePostResponse(w http.ResponseWriter) error {
	return x.write(w)
}

func (x response) VisitRunTriggerNowV1TriggersTriggerIdRunPostResponse(w http.ResponseWriter) error {
	return x.write(w)
}

// firingError is how both routes answer a failed firing. A refused agent is a 403 here; Python's
// blanket except turned it into a 500.
func (s *Server) firingError(ctx context.Context, id string, err error) error {
	switch {
	case errors.Is(err, domain.ErrNotFound):
		return notFound(id, err)
	case errors.Is(err, authz.ErrDenied):
		return err
	case errors.Is(err, authn.ErrUnauthenticated):
		return httpx.HTTPError(http.StatusUnauthorized, "Authenticated user required")
	}
	s.log.ErrorContext(ctx, "Failed to fire trigger", "trigger_id", id, "error", err)
	return httpx.HTTPError(http.StatusInternalServerError, "Internal server error")
}

// ExecuteTriggerV1TriggersTriggerIdExecutePost replays events through the trigger as the caller.
func (s *Server) ExecuteTriggerV1TriggersTriggerIdExecutePost(ctx context.Context, req gen.ExecuteTriggerV1TriggersTriggerIdExecutePostRequestObject) (gen.ExecuteTriggerV1TriggersTriggerIdExecutePostResponseObject, error) {
	id := req.TriggerId.String()
	evs := []any{}
	if req.Body != nil && req.Body.Events != nil {
		for _, e := range *req.Body.Events {
			evs = append(evs, e)
		}
	}
	f, err := s.svc.FireManually(ctx, id, map[string]any{"events": evs})
	if err != nil {
		return nil, s.firingError(ctx, id, err)
	}
	if f.Execution == nil {
		return response{status: http.StatusOK, body: map[string]any{"status": "skipped", "trigger_id": id}}, nil
	}
	return response{status: http.StatusOK, body: map[string]any{
		"status": f.Execution.Status, "trigger_id": id, "execution_id": f.Execution.ID,
		"task_id": f.Execution.TaskID, "reason": f.Execution.ErrorMessage,
	}}, nil
}

// RunTriggerNowV1TriggersTriggerIdRunPost fires the trigger once, now, with no event.
func (s *Server) RunTriggerNowV1TriggersTriggerIdRunPost(ctx context.Context, req gen.RunTriggerNowV1TriggersTriggerIdRunPostRequestObject) (gen.RunTriggerNowV1TriggersTriggerIdRunPostResponseObject, error) {
	id := req.TriggerId.String()
	f, err := s.svc.FireManually(ctx, id, map[string]any{"events": []any{}})
	if err != nil {
		return nil, s.firingError(ctx, id, err)
	}
	if f.Execution == nil {
		return nil, httpx.HTTPError(http.StatusInternalServerError, "Trigger run produced no execution")
	}
	return response{status: http.StatusOK, body: runResponse(req.TriggerId, f.Execution)}, nil
}

func runResponse(trigger uuid.UUID, ex *service.ExecutionRef) gen.TriggerRunResponse {
	out := gen.TriggerRunResponse{TriggerId: trigger, Status: gen.TriggerRunResponseStatus("skipped"), Reason: ex.ErrorMessage}
	out.ExecutionId, _ = uuid.Parse(ex.ID)
	if ex.TaskID != nil {
		if t, err := uuid.Parse(*ex.TaskID); err == nil {
			out.TaskId = &t
			out.Status = gen.TriggerRunResponseStatus("started")
		}
	}
	return out
}
