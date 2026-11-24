package router

import (
	"context"
	"errors"
	"slices"
	"strconv"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
)

// NoEventsReason is the reason of a processor run that wrote nothing.
const NoEventsReason = "process() wrote no events"

// ProcessorHandler runs a processor's code in the sandbox in Prepare and writes its events in Finish.
// A failure of the code is an error reaction; a sandbox that cannot run it is retried.
type ProcessorHandler struct{ d Deps }

func (h *ProcessorHandler) Prepare(ctx context.Context, sub domain.Subscription, e domain.Event) (Finish, error) {
	limit := h.d.Settings.ForwardDepth
	depth := e.Depth + 1
	if depth > limit {
		return settled(errorResult(depthExceeded(depth, limit))), nil
	}
	if slices.Contains(sub.OutputStreamIDs, sub.StreamID) {
		return settled(errorResult("a processor never writes to its own input stream")), nil
	}
	if sub.Code == nil || *sub.Code == "" {
		return settled(errorResult("the processor has no code")), nil
	}
	outputs, err := h.run(ctx, sub, e)
	if f, ok := asFailed(err); ok {
		h.d.Log.InfoContext(ctx, "Processor failed on an event", "subscription_id", sub.ID, "event_id", e.ID, "error", f.Reason)
		return settled(errorResult(f.Reason)), nil
	} else if err != nil {
		return nil, err
	}
	return func(ctx context.Context, sess db.Session) (store.Result, error) {
		return h.write(ctx, sess, sub, e, outputs, depth)
	}, nil
}

func (h *ProcessorHandler) run(ctx context.Context, sub domain.Subscription, e domain.Event) ([]ProcessorOutput, error) {
	payload, err := EventPayload(e)
	if err != nil {
		return nil, err
	}
	command, err := HarnessCommand(*sub.Code, payload)
	if err != nil {
		return nil, err
	}
	if h.d.Runner == nil {
		return nil, service.ErrProcessorRuntimeUnavailable
	}
	run, err := h.d.Runner.Run(ctx, sub.WorkspaceID, SandboxSession(sub.ID), command, ProcessorTimeout, MaxResultBytes)
	if err != nil {
		return nil, err
	}
	return OutputsOf(run)
}

func (h *ProcessorHandler) write(ctx context.Context, sess db.Session, sub domain.Subscription, e domain.Event,
	outputs []ProcessorOutput, depth int,
) (store.Result, error) {
	declared, err := store.Streams{}.StreamNames(ctx, sess, sub.OutputStreamIDs)
	if err != nil {
		return store.Result{}, err
	}
	routed, err := ResolveStreams(outputs, declared, sub.StreamID)
	if f, ok := asFailed(err); ok {
		h.d.Log.InfoContext(ctx, "Processor failed on an event", "subscription_id", sub.ID, "event_id", e.ID, "error", f.Reason)
		return errorResult(f.Reason), nil
	} else if err != nil {
		return store.Result{}, err
	}
	if len(routed) == 0 {
		return skippedResult(NoEventsReason), nil
	}
	written := []string{}
	for i, r := range routed {
		id, err := domain.ProcessorOutputID(sub.ID, e.ID, i)
		if err != nil {
			return store.Result{}, err
		}
		key := e.ID + ":" + strconv.Itoa(i)
		if r.Output.Key != nil {
			key = *r.Output.Key
		}
		ev := derived(e, sub, r.StreamID, id, "processor:"+sub.ID, key, depth)
		ev.Kind = r.Output.Kind
		ev.Data = r.Output.Data
		if _, err := h.d.Service.Append(ctx, sess, ev); errors.Is(err, domain.ErrStreamNotFound) {
			h.d.Log.InfoContext(ctx, "Processor skips an output that no longer exists", "subscription_id", sub.ID, "stream_id", r.StreamID)
			continue
		} else if err != nil {
			return store.Result{}, err
		}
		written = append(written, id)
	}
	return store.Result{Verdict: domain.VerdictReacted, DerivedEventIDs: written}, nil
}
