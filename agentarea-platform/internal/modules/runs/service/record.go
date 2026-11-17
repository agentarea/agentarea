package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// RecordInput is what a run records at once (record.py RecordRequest).
type RecordInput struct {
	TaskID      string
	ExecutionID string
	Rows        []domain.Entry
	Live        []domain.StoredEvent
	Status      *domain.StatusUpdate
}

// RecordOutput counts what was recorded.
type RecordOutput struct{ Rows, Events int }

// Record appends the run's log rows and, in the same transaction, the task's
// status and result, the ledger lines and audit rows its event rows stand
// for, and the legacy task_events rows; then publishes each event row and
// each person's message to tasks.events and broadcasts the live signals.
// Every write is keyed by the workflow's ids, so a retry writes nothing twice.
func (s *Service) Record(ctx context.Context, p Principal, in RecordInput) (RecordOutput, error) {
	ws, err := workspace(p)
	if err != nil {
		return RecordOutput{}, err
	}
	now := s.now()
	for i := range in.Rows {
		in.Rows[i].ExecutionID = in.ExecutionID
		in.Rows[i].Meta = domain.StorableMap(in.Rows[i].Meta)
	}
	var stored []domain.StoredEvent
	for _, row := range in.Rows {
		if e, ok := domain.RowEvent(row, now); ok {
			stored = append(stored, e)
		}
	}
	var audits []domain.AuditLine
	var costs []domain.CostLine
	currency := string(s.d.Pricing.Currency())
	for _, e := range stored {
		if line, ok := domain.ToolAudit(e, p.UserID); ok {
			audits = append(audits, line)
		}
		costs = append(costs, domain.CostLines(e, currency)...)
	}
	if len(audits) > 0 && s.d.Audit == nil {
		return RecordOutput{}, errors.New("the record holds audited events but no audit sink is wired")
	}
	rows, err := s.offloadBodies(ctx, p.WorkspaceID, in.TaskID, in.Rows)
	if err != nil {
		return RecordOutput{}, err
	}
	statusChanged := false
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		task, err := s.store.Task(ctx, tx, in.TaskID)
		if err != nil {
			return err
		}
		for _, row := range rows {
			if err := s.store.InsertEntry(ctx, tx, task, row, p.UserID); err != nil {
				return err
			}
		}
		if in.Status != nil {
			o := domain.OutcomeOf(*in.Status)
			if _, err := s.store.SetOutcome(ctx, tx, in.TaskID, o, now); err != nil {
				return err
			}
			statusChanged = in.Status.Status != task.Status
		}
		for _, l := range costs {
			chain := task
			if l.TaskID != task.ID {
				if chain, err = s.store.Task(ctx, tx, l.TaskID); errors.Is(err, store.ErrTaskNotFound) {
					chain = store.TaskRef{}
				} else if err != nil {
					return err
				}
			}
			if _, err := s.store.InsertCostLine(ctx, tx, l, p.UserID, chain); err != nil {
				return err
			}
		}
		for _, a := range audits {
			a.Metadata = domain.StorableMap(a.Metadata)
			if err := s.d.Audit.RecordOnce(ctx, tx, auditRecord(a)); err != nil {
				return err
			}
		}
		for _, e := range stored {
			taskID, _ := e.Data["task_id"].(string)
			if taskID == "" {
				taskID = in.TaskID
			}
			if err := s.store.InsertTaskEvent(ctx, tx, taskID, e, p.UserID, now); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return RecordOutput{}, recordFailure(err)
	}
	if statusChanged {
		s.recordRunTransition(*in.Status)
	}
	if err := s.publish(ctx, p, in, rows, now); err != nil {
		return RecordOutput{}, err
	}
	return RecordOutput{Rows: len(in.Rows), Events: len(stored) + len(in.Live)}, nil
}

// recordFailure: a deleted task stays deleted and a row the database refuses
// is refused again, so neither is retried.
func recordFailure(err error) error {
	if errors.Is(err, store.ErrTaskNotFound) {
		return nonRetryable("TaskNotFound", err.Error(), err)
	}
	if reason, ok := store.Refused(err); ok {
		return nonRetryable("TaskLogRejected", "the task log refused the run's record: "+reason, err)
	}
	return err
}

// offloadBodies stores row bodies over BodyOffloadBytes outside their row.
func (s *Service) offloadBodies(ctx context.Context, workspaceID, taskID string, rows []domain.Entry) ([]domain.Entry, error) {
	out := make([]domain.Entry, len(rows))
	for i, row := range rows {
		if _, err := uuid.Parse(row.EventID); err != nil {
			return nil, nonRetryable("ValueError", fmt.Sprintf("log row %d of task %s has no event_id", row.Seq, taskID), err)
		}
		row.Content = domain.StorableText(row.Content)
		if len(row.Content) > domain.BodyOffloadBytes {
			ref := logBodyKey(workspaceID, taskID, row.EventID, "content")
			if err := s.putText(ctx, ref, row.Content, "text/plain; charset=utf-8"); err != nil {
				return nil, err
			}
			row.BodyRef, row.Content = ref, ""
		}
		if row.ToolCalls != nil {
			encoded, err := json.Marshal(domain.ToolCallsJSON(row.ToolCalls))
			if err != nil {
				return nil, err
			}
			if len(encoded) > domain.BodyOffloadBytes {
				ref := logBodyKey(workspaceID, taskID, row.EventID, "tool_calls")
				if err := s.putText(ctx, ref, string(encoded), "text/plain; charset=utf-8"); err != nil {
					return nil, err
				}
				meta := map[string]any{}
				for k, v := range row.Meta {
					meta[k] = v
				}
				meta[domain.ToolCallsRef] = ref
				row.Meta, row.ToolCalls = meta, nil
			}
		}
		out[i] = row
	}
	return out, nil
}

func logBodyKey(workspaceID, taskID, eventID, part string) string {
	name := eventID
	if part != "content" {
		name += "." + part
	}
	return fmt.Sprintf("tasks/%s/%s/log/%s.txt", workspaceID, taskID, name)
}

// resolveBodies reads back the bodies stored outside their rows.
func (s *Service) resolveBodies(ctx context.Context, rows []domain.Entry) ([]domain.Entry, error) {
	for i, e := range rows {
		if e.BodyRef != "" {
			body, err := s.getText(ctx, e.BodyRef)
			if err != nil {
				return nil, fmt.Errorf("log body %s: %w", e.BodyRef, err)
			}
			rows[i].Content = body
		}
		if ref, ok := e.Meta[domain.ToolCallsRef].(string); ok {
			body, err := s.getText(ctx, ref)
			if err != nil {
				return nil, fmt.Errorf("log body %s: %w", ref, err)
			}
			calls, err := domain.ParseToolCalls([]byte(body))
			if err != nil {
				return nil, err
			}
			rows[i].ToolCalls = calls
		}
	}
	return rows, nil
}

func (s *Service) publish(ctx context.Context, p Principal, in RecordInput, rows []domain.Entry, now time.Time) error {
	if s.d.Events == nil {
		return errors.New("the record activity publishes task events; it needs a broker")
	}
	bodies := domain.BodiesOf(rows)
	for _, row := range rows {
		eventType, data, ok := domain.FeedEvent(row, &bodies)
		if !ok {
			continue
		}
		ts := now
		if row.OccurredAt != nil {
			ts = *row.OccurredAt
		}
		seq := row.Seq
		e := taskEvent(in.TaskID, p.WorkspaceID, eventType, row.EventID, ts, domain.StorableMap(data), &seq)
		if err := s.d.Events.Submit(ctx, e); err != nil {
			return fmt.Errorf("publish %s of task %s: %w", eventType, in.TaskID, err)
		}
	}
	for _, live := range in.Live {
		if !domain.LiveOnly(live.Type) {
			return nonRetryable("ValueError", fmt.Sprintf("%s is stored; record it as an event row", live.Type), nil)
		}
		ts := live.Timestamp
		if ts.IsZero() {
			ts = now
		}
		e := taskEvent(in.TaskID, "", live.Type, live.ID, ts, live.Data, nil)
		if err := s.d.Events.Broadcast(ctx, e); err != nil {
			return fmt.Errorf("broadcast %s of task %s: %w", live.Type, in.TaskID, err)
		}
	}
	return nil
}

// UpdateGovernanceSnapshot stores the policy revision a waiting run resumes under.
func (s *Service) UpdateGovernanceSnapshot(ctx context.Context, p Principal, taskID string, snapshot any) error {
	ws, err := workspace(p)
	if err != nil {
		return err
	}
	raw, err := json.Marshal(snapshot)
	if err != nil {
		return err
	}
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		return err
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		ok, err := s.store.MergeMetadata(ctx, tx, taskID, map[string]any{"governance_snapshot": value}, s.now())
		if err != nil {
			return err
		}
		if !ok {
			s.d.Log.WarnContext(ctx, "governance snapshot not stored: task not found", "task_id", taskID)
		}
		return nil
	})
}
