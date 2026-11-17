package service

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// The last real call to each instance, stamped off the call path
// (dispatch_stamps.py): a call only queues its outcome, the process's writer
// loop writes the queue to last_dispatch. Like Python's, the queue is the
// process's, so every Service of the process feeds the one writer.
const (
	stampQueueSize = 1000
	stampBatch     = 100
	stampInterval  = 500 * time.Millisecond
)

type stamp struct {
	id    string
	value map[string]any
}

//nolint:gochecknoglobals // one queue per process, as Python's; it outlives a Service rebuilt by Use
var stamps = make(chan stamp, stampQueueSize)

// stampDispatch queues the outcome of a call to id; errMsg marks it failed.
// It never blocks: a full queue drops the stamp.
func (s *Service) stampDispatch(id string, errMsg *string) {
	status := domain.VerifySucceeded
	var e any
	if errMsg != nil {
		status, e = domain.VerifyFailed, *errMsg
	}
	v := map[string]any{"schema_version": domain.VerificationSchema, "status": status,
		"at": s.d.Now().UTC().Format("2006-01-02T15:04:05.999999-07:00"), "error": e}
	select {
	case stamps <- stamp{id: id, value: v}:
	default:
		s.d.Log.Warn("dispatch stamp dropped: the queue is full", "instance_id", id)
	}
}

// RunDispatchStamps writes queued stamps every half second until ctx ends,
// then drains the queue once more.
func (s *Service) RunDispatchStamps(ctx context.Context) error {
	t := time.NewTicker(stampInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			flush := context.WithoutCancel(ctx)
			for s.FlushDispatchStamps(flush) > 0 {
			}
			return nil
		case <-t.C:
			s.FlushDispatchStamps(ctx)
		}
	}
}

// FlushDispatchStamps writes one batch, the latest stamp per instance; it
// returns how many stamps it took off the queue.
func (s *Service) FlushDispatchStamps(ctx context.Context) int {
	latest := map[uuid.UUID]map[string]any{}
	taken := 0
loop:
	for taken < stampBatch {
		select {
		case st := <-stamps:
			taken++
			id, err := uuid.Parse(st.id)
			if err != nil {
				s.d.Log.Error("dropping a dispatch stamp for a malformed instance id", "instance_id", st.id)
				continue
			}
			latest[id] = st.value
		default:
			break loop
		}
	}
	if len(latest) == 0 {
		return taken
	}
	err := s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		for id, v := range latest {
			if err := s.d.Instances.StampLastDispatch(ctx, q, id, v); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		s.d.Log.Error("writing MCP dispatch stamps failed", "count", len(latest), "error", err)
	}
	return taken
}
