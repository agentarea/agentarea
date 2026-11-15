package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// Task event types the task-event consumers act on (events/contract.py).
const (
	TaskCompleted     = "task.completed"
	TaskFailed        = "task.failed"
	TaskCancelled     = "task.cancelled"
	ApprovalRequested = "approval.requested"
	InputRequest      = "input.request"
)

// PlatformPrincipal is PLATFORM_PRINCIPAL_ID: who creates a workspace's platform stream.
const PlatformPrincipal = "platform"

const platformSummaryChars = 500

// platformStatuses are the task events the platform stream carries, with the status each reports.
func platformStatuses() map[string]string {
	return map[string]string{
		TaskCompleted: "completed", TaskFailed: "failed", TaskCancelled: "cancelled",
		ApprovalRequested: "waiting_for_approval", InputRequest: "waiting_for_input",
	}
}

// TaskEventScope is the workspace and the task a task event names; ErrUnprocessable when it
// names neither.
func TaskEventScope(e events.IntegrationEvent) (scope.Workspace, string, error) {
	task, err := uuid.Parse(e.Subject)
	if err != nil {
		return scope.Workspace{}, "", fmt.Errorf("%w: task event %s names no task", events.ErrUnprocessable, e.ID)
	}
	ws, err := scope.NewWorkspace(e.Extensions["workspace"], "")
	if err != nil {
		return scope.Workspace{}, "", fmt.Errorf("%w: task event %s names no workspace", events.ErrUnprocessable, e.ID)
	}
	return ws, task.String(), nil
}

// CountTaskOutcome is TriggerRunOutcomes.handle: the end of a task a trigger started counts
// towards the trigger's failure_threshold. A completed task resets the count; a failed one marks
// the firing that started it failed and counts once, switching the trigger off at its threshold.
// A cancelled task counts neither way. store.ErrFiringNotRecorded is returned (redelivered) while
// the firing that started the task is not recorded yet.
func (s *Service) CountTaskOutcome(ctx context.Context, e events.IntegrationEvent) error {
	if e.Type != TaskCompleted && e.Type != TaskFailed {
		return nil
	}
	ws, taskID, err := TaskEventScope(e)
	if err != nil {
		return err
	}
	task, ok, err := s.d.TaskOutcomes.OutcomeTask(ctx, ws, taskID)
	if err != nil || !ok || task.OriginType != "trigger" || task.OriginID == "" {
		return err
	}
	triggerID, err := uuid.Parse(task.OriginID)
	if err != nil {
		s.log.ErrorContext(ctx, "Task names a trigger origin that is no id", "task_id", taskID, "origin_id", task.OriginID)
		return nil
	}
	failed := e.Type == TaskFailed
	var reason *string
	if failed {
		reason = firstText(e.Data, "error", "failure_reason")
	}
	now := s.now()
	var disabled *domain.Trigger
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		found, err := store.Router{}.LockTrigger(ctx, sess, triggerID)
		if err != nil {
			return err
		}
		if !found {
			s.log.InfoContext(ctx, "Trigger is gone; the end of its task is not counted", "trigger_id", triggerID.String(), "task_id", taskID)
			return nil
		}
		if !failed {
			return store.Router{}.ResetFailures(ctx, sess, triggerID, now)
		}
		marked, err := store.Router{}.MarkRunFailed(ctx, sess, triggerID, uuid.MustParse(taskID), reason, now)
		if err != nil || !marked {
			return err
		}
		disabled, err = s.countFailure(ctx, sess, triggerID.String(), task.Owner, now)
		return err
	})
	if err != nil {
		return err
	}
	if disabled != nil {
		s.applySchedule(ctx, *disabled)
	}
	return nil
}

// ProjectTaskEvent is PlatformProjection.handle: a task that completed, failed, was cancelled or
// waits for an approval or an answer becomes an event of its workspace's platform stream,
// created on first use, keyed so a redelivery appends nothing twice.
func (s *Service) ProjectTaskEvent(ctx context.Context, e events.IntegrationEvent) error {
	status, ok := platformStatuses()[e.Type]
	if !ok {
		return nil
	}
	ws, taskID, err := TaskEventScope(e)
	if err != nil {
		return err
	}
	task, ok, err := s.d.TaskOutcomes.OutcomeTask(ctx, ws, taskID)
	if err != nil {
		return err
	}
	if !ok {
		s.log.InfoContext(ctx, "Task of event is gone; not projected", "task_id", taskID, "event_id", e.ID)
		return nil
	}
	stream, source, err := s.ensurePlatformStream(ctx, ws)
	if err != nil {
		return err
	}
	subject, causation, sourceType := task.ID, e.ID, domain.PlatformSourceType
	ev := domain.Event{
		Kind: e.Type, Source: domain.PlatformSourceType, Subject: &subject, OccurredAt: e.Time,
		CausationID: &causation, StreamID: stream.ID, WorkspaceID: ws.ID(), CreatedBy: task.Owner,
		EventKey: PlatformEventKey(e.Type, e.ID, e.Data), Depth: task.Depth + 1, SourceID: &source.ID, SourceType: &sourceType,
		Data: map[string]any{"body": PlatformEventData(e.Type, status, task.ID, task.AgentID, e.Data)},
	}
	if task.CorrelationID != "" {
		corr := task.CorrelationID
		ev.CorrelationID = &corr
	}
	return s.read(ctx, ws, func(sess db.Session) error {
		_, err := s.Append(ctx, sess, ev)
		return err
	})
}

// ensurePlatformStream is ensure_platform_stream: the workspace's platform stream and its one
// source, created on first use; two writers meet on the stream's unique name.
func (s *Service) ensurePlatformStream(ctx context.Context, ws scope.Workspace) (domain.Stream, domain.Source, error) {
	var st domain.Stream
	var src domain.Source
	now := s.now()
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		found, ok, err := s.ss.GetPlatformStream(ctx, sess)
		if err != nil {
			return err
		}
		st = found
		if !ok {
			st, err = s.ss.InsertStream(ctx, sess, domain.Stream{
				ID: uuid.NewString(), Name: domain.PlatformStreamName, Description: "What happened to this workspace's tasks.",
				Kind: domain.StreamPlatform, CreatedBy: PlatformPrincipal,
			}, now)
			switch {
			case errors.Is(err, domain.ErrNameTaken):
				if st, ok, err = s.ss.GetPlatformStream(ctx, sess); err == nil && !ok {
					err = domain.NameTaken(domain.PlatformStreamName)
				}
				if err != nil {
					return err
				}
			case err != nil:
				return err
			default:
				if err := authz.GrantResourceOwner(ctx, s.d.Graph, st.ID, ws.ID(), authz.UserSubject(PlatformPrincipal), authz.OwnerRelations()); err != nil {
					return err
				}
			}
		}
		sources, err := s.ss.ListSources(ctx, sess, uuid.MustParse(st.ID))
		if err != nil {
			return err
		}
		if len(sources) > 0 {
			src = sources[0]
			return nil
		}
		id, slug := uuid.NewString(), domain.PlatformSourceType
		src, err = s.ss.InsertSource(ctx, sess, domain.Source{
			ID: id, StreamID: st.ID, Kind: domain.SourcePlatform, SourceType: &slug, WebhookConfig: map[string]any{},
			CredentialKey: &id, CreatedBy: PlatformPrincipal,
		}, now)
		return err
	})
	return st, src, err
}

// PlatformEventData is platform_event_data: what happened to the task in a few fields; tool
// output, arguments and error details stay in the task log.
func PlatformEventData(kind, status, taskID, agentID string, data map[string]any) map[string]any {
	out := map[string]any{"task_id": taskID, "agent_id": agentID, "kind": kind, "status": status}
	put := func(k string, v any) {
		if text, ok := platformSummary(v); ok {
			out[k] = text
		}
	}
	switch kind {
	case TaskCompleted:
		put("result", firstTruthy(data, "final_response", "result"))
	case TaskFailed, TaskCancelled:
		put("error", data["error"])
		put("failure_reason", data["failure_reason"])
	case ApprovalRequested:
		put("tool_name", data["tool_name"])
		put("reason", firstTruthy(data, "reason", "message"))
	case InputRequest:
		put("question", data["question"])
	}
	if cost, ok := data["total_cost"]; ok && cost != nil {
		out["cost"] = cost
	}
	return out
}

// PlatformEventKey is platform_event_key: the task event's id; a request the run records twice
// is keyed by the request.
func PlatformEventKey(kind, eventID string, data map[string]any) string {
	if id := firstTruthy(data, "escalation_id"); kind == ApprovalRequested && id != nil {
		return "approval:" + fmt.Sprint(id)
	}
	if id := firstTruthy(data, "input_request_id"); kind == InputRequest && id != nil {
		return "input:" + fmt.Sprint(id)
	}
	return eventID
}

func platformSummary(v any) (string, bool) {
	if v == nil || v == "" {
		return "", false
	}
	text, ok := v.(string)
	if !ok {
		var buf bytes.Buffer
		enc := json.NewEncoder(&buf)
		enc.SetEscapeHTML(false)
		if err := enc.Encode(v); err != nil {
			text = fmt.Sprint(v)
		} else {
			text = string(bytes.TrimSuffix(buf.Bytes(), []byte("\n")))
		}
	}
	text = domain.MaskInlineSecrets(text)
	if r := []rune(text); len(r) > platformSummaryChars {
		return string(r[:platformSummaryChars]) + "…", true
	}
	return text, true
}

// firstTruthy is `data.get(a) or data.get(b)`: the first value Python counts as true, nil when none.
func firstTruthy(data map[string]any, keys ...string) any {
	for _, k := range keys {
		if v := data[k]; truthy(v) {
			return v
		}
	}
	return nil
}

func firstText(data map[string]any, keys ...string) *string {
	v := firstTruthy(data, keys...)
	if v == nil {
		return nil
	}
	text, ok := v.(string)
	if !ok {
		text = fmt.Sprint(v)
	}
	return &text
}

func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case bool:
		return x
	case float64:
		return x != 0
	case json.Number:
		f, err := x.Float64()
		return err != nil || f != 0
	case map[string]any:
		return len(x) > 0
	case []any:
		return len(x) > 0
	}
	return true
}
