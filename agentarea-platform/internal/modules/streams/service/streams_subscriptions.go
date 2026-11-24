package service

import (
	"context"
	"fmt"
	"slices"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// OutcomesMax is the most outcomes one listing returns.
const OutcomesMax = 500

// ListSubscriptions is list_subscriptions.
func (s *Service) ListSubscriptions(ctx context.Context, streamID string) ([]domain.Subscription, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	u, err := parseStreamID(streamID)
	if err != nil {
		return nil, err
	}
	var out []domain.Subscription
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		out, err = s.ss.ListSubscriptions(ctx, sess, u)
		return err
	})
	return out, err
}

// writableOutputs is _writable_outputs: the outputs deduplicated in order, each locked, existing
// and not the platform stream.
func (s *Service) writableOutputs(ctx context.Context, sess db.Session, streamID string, outputs []string, writer string) ([]string, error) {
	var deduped []string
	for _, o := range outputs {
		if !slices.Contains(deduped, o) {
			deduped = append(deduped, o)
		}
	}
	if _, err := s.getStream(ctx, sess, streamID); err != nil {
		return nil, err
	}
	found, err := s.ss.LockExisting(ctx, sess, deduped)
	if err != nil {
		return nil, err
	}
	for _, o := range deduped {
		if !found[o] {
			return nil, domain.StreamNotFound(o)
		}
		st, err := s.getStream(ctx, sess, o)
		if err != nil {
			return nil, err
		}
		if st.Kind == domain.StreamPlatform {
			return nil, domain.Fail(domain.ErrManagedByPlatform,
				fmt.Sprintf("Only the platform writes to the platform stream; %s into another stream", writer))
		}
	}
	return deduped, nil
}

// requireOutputs asks edit on each output stream, as the routes do before the service runs.
func (s *Service) requireOutputs(ctx context.Context, c authn.Caller, outputs []string) error {
	for _, o := range outputs {
		if err := s.perms.Require(ctx, c, "edit", "stream", o); err != nil {
			return err
		}
	}
	return nil
}

func canonicalOutputs(ids []string) ([]string, error) {
	out := make([]string, len(ids))
	for i, id := range ids {
		u, err := uuid.Parse(id)
		if err != nil {
			return nil, domain.Invalid(fmt.Sprintf("output_stream_ids.%d: Input should be a valid UUID", i))
		}
		out[i] = u.String()
	}
	return out, nil
}

// CreateForward is create_forward: the caller edits every output; every matching event is copied.
func (s *Service) CreateForward(ctx context.Context, streamID string, outputs []string, filter domain.EventFilter) (domain.Subscription, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Subscription{}, err
	}
	if outputs, err = canonicalOutputs(outputs); err != nil {
		return domain.Subscription{}, err
	}
	if err := s.requireOutputs(ctx, c, outputs); err != nil {
		return domain.Subscription{}, err
	}
	if len(outputs) == 0 {
		return domain.Subscription{}, domain.Fail(domain.ErrForwardLoop, "A forward needs at least one output stream")
	}
	if slices.Contains(outputs, streamID) {
		return domain.Subscription{}, domain.Fail(domain.ErrForwardLoop, "A forward may not write into its own input stream")
	}
	return s.addWriter(ctx, c, streamID, outputs, filter, domain.SubForward, nil, "forward")
}

func (s *Service) addWriter(ctx context.Context, c authn.Caller, streamID string, outputs []string, filter domain.EventFilter,
	kind string, code *string, writer string) (domain.Subscription, error) {
	var out domain.Subscription
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		outs, err := s.writableOutputs(ctx, sess, streamID, outputs, writer)
		if err != nil {
			return err
		}
		out, err = s.ss.InsertSubscription(ctx, sess, domain.Subscription{
			ID: uuid.NewString(), StreamID: streamID, Kind: kind, Filter: filter.Dump(), OutputStreamIDs: outs,
			Status: domain.SubActive, Code: code, CreatedBy: c.UserID,
		}, s.now())
		if err != nil {
			return err
		}
		return subscriptionsChanged(ctx, sess, c.UserID, streamID)
	})
	return out, err
}

func (s *Service) subscriptionIn(ctx context.Context, sess db.Session, streamID, subID string) (domain.Subscription, error) {
	su, err1 := uuid.Parse(streamID)
	id, err2 := uuid.Parse(subID)
	if err1 != nil || err2 != nil {
		return domain.Subscription{}, domain.SubscriptionNotFound(subID)
	}
	sub, ok, err := s.ss.GetSubscription(ctx, sess, su, id)
	if err != nil {
		return domain.Subscription{}, err
	}
	if !ok {
		return domain.Subscription{}, domain.SubscriptionNotFound(subID)
	}
	return sub, nil
}

// existingOutputs is existing_outputs: the writer's outputs that still exist.
func (s *Service) existingOutputs(ctx context.Context, sess db.Session, sub domain.Subscription) ([]string, error) {
	found, err := s.ss.LockExisting(ctx, sess, sub.OutputStreamIDs)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, o := range sub.OutputStreamIDs {
		if found[o] {
			out = append(out, o)
		}
	}
	return out, nil
}

// DeleteForward is delete_forward: the caller edits every output that still exists; a trigger's
// subscription is refused, it goes with its trigger.
func (s *Service) DeleteForward(ctx context.Context, streamID, subID string) error {
	return s.deleteWriter(ctx, streamID, subID, func(sub domain.Subscription) error {
		if sub.Kind != domain.SubForward {
			return domain.NotAForward(sub.ID, sub.Kind, sub.TriggerID)
		}
		return nil
	})
}

// DeleteProcessor is delete_processor: the events it wrote stay.
func (s *Service) DeleteProcessor(ctx context.Context, streamID, subID string) error {
	return s.deleteWriter(ctx, streamID, subID, func(sub domain.Subscription) error {
		if sub.Kind != domain.SubProcessor {
			return domain.NotAProcessor(sub.ID)
		}
		return nil
	})
}

func (s *Service) deleteWriter(ctx context.Context, streamID, subID string, kindOK func(domain.Subscription) error) error {
	c, err := callerOf(ctx)
	if err != nil {
		return err
	}
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		sub, err := s.subscriptionIn(ctx, sess, streamID, subID)
		if err != nil {
			return err
		}
		if err := kindOK(sub); err != nil {
			return err
		}
		outs, err := s.existingOutputs(ctx, sess, sub)
		if err != nil {
			return err
		}
		if err := s.requireOutputs(ctx, c, outs); err != nil {
			return err
		}
		ok, err := s.ss.DeleteSubscription(ctx, sess, uuid.MustParse(sub.ID))
		if err != nil {
			return err
		}
		if !ok {
			return domain.SubscriptionNotFound(subID)
		}
		return subscriptionsChanged(ctx, sess, c.UserID, sub.StreamID)
	})
}

func processorOutputsAllowed(streamID string, outputs []string) error {
	if len(outputs) == 0 {
		return domain.Fail(domain.ErrProcessorLoop, "A processor needs at least one output stream")
	}
	if slices.Contains(outputs, streamID) {
		return domain.Fail(domain.ErrProcessorLoop, "A processor may not write into its own input stream")
	}
	return nil
}

// CreateProcessor is create_processor: code checked, outputs writable by the caller.
func (s *Service) CreateProcessor(ctx context.Context, streamID string, outputs []string, code string, filter domain.EventFilter) (domain.Subscription, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Subscription{}, err
	}
	if outputs, err = canonicalOutputs(outputs); err != nil {
		return domain.Subscription{}, err
	}
	if err := s.requireOutputs(ctx, c, outputs); err != nil {
		return domain.Subscription{}, err
	}
	if err := processorOutputsAllowed(streamID, outputs); err != nil {
		return domain.Subscription{}, err
	}
	if err := domain.CheckProcessorCode(code); err != nil {
		return domain.Subscription{}, err
	}
	return s.addWriter(ctx, c, streamID, outputs, filter, domain.SubProcessor, &code, "write")
}

// ProcessorPatch is a ProcessorUpdate: nil keeps a field.
type ProcessorPatch struct {
	Code    *string
	Outputs []string
	Filter  *domain.EventFilter
}

// UpdateProcessor is update_processor: the caller edits every output it has and is given.
func (s *Service) UpdateProcessor(ctx context.Context, streamID, subID string, p ProcessorPatch) (domain.Subscription, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Subscription{}, err
	}
	if p.Outputs != nil {
		if p.Outputs, err = canonicalOutputs(p.Outputs); err != nil {
			return domain.Subscription{}, err
		}
	}
	var out domain.Subscription
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		sub, err := s.subscriptionIn(ctx, sess, streamID, subID)
		if err != nil {
			return err
		}
		if sub.Kind != domain.SubProcessor {
			return domain.NotAProcessor(sub.ID)
		}
		existing, err := s.existingOutputs(ctx, sess, sub)
		if err != nil {
			return err
		}
		check := append(slices.Clone(existing), p.Outputs...)
		slices.Sort(check)
		if err := s.requireOutputs(ctx, c, slices.Compact(check)); err != nil {
			return err
		}
		if p.Code != nil {
			if err := domain.CheckProcessorCode(*p.Code); err != nil {
				return err
			}
			sub.Code = p.Code
		}
		if p.Outputs != nil {
			if err := processorOutputsAllowed(streamID, p.Outputs); err != nil {
				return err
			}
			outs, err := s.writableOutputs(ctx, sess, streamID, p.Outputs, "write")
			if err != nil {
				return err
			}
			sub.OutputStreamIDs = outs
		}
		if p.Filter != nil {
			sub.Filter = p.Filter.Dump()
		}
		if out, err = s.ss.UpdateProcessor(ctx, sess, sub, s.now()); err != nil {
			return err
		}
		return subscriptionsChanged(ctx, sess, c.UserID, streamID)
	})
	return out, err
}

// Outcome is a reaction as OutcomeResponse reads it, with its subscription's kind.
type Outcome struct {
	domain.Reaction
	SubscriptionKind string
	TriggerIDOf      *string
}

func outcomeOf(r domain.Reaction, sub *domain.Subscription) Outcome {
	o := Outcome{Reaction: r, SubscriptionKind: "deleted", TriggerIDOf: r.TriggerID}
	if sub != nil {
		o.SubscriptionKind, o.TriggerIDOf = sub.Kind, sub.TriggerID
	}
	return o
}

// ListOutcomes is list_outcomes: a subscription's newest reactions.
func (s *Service) ListOutcomes(ctx context.Context, streamID, subID string, limit int) ([]Outcome, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	var out []Outcome
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		subs, err := s.listSubscriptions(ctx, sess, streamID)
		if err != nil {
			return err
		}
		idx := slices.IndexFunc(subs, func(x domain.Subscription) bool { return x.ID == subID })
		if idx < 0 {
			return domain.Fail(domain.ErrSubscriptionNotFound, "Subscription not found in stream")
		}
		rows, err := s.ss.ReactionsForSubscription(ctx, sess, uuid.MustParse(subs[idx].ID), int32(limit)) //nolint:gosec // bounded by the route
		if err != nil {
			return err
		}
		for _, r := range rows {
			out = append(out, outcomeOf(r, &subs[idx]))
		}
		return nil
	})
	return out, err
}

func (s *Service) listSubscriptions(ctx context.Context, sess db.Session, streamID string) ([]domain.Subscription, error) {
	u, err := uuid.Parse(streamID)
	if err != nil {
		return nil, nil
	}
	return s.ss.ListSubscriptions(ctx, sess, u)
}
