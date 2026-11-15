package store

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// ReactionsForEventIDs lists the subscriptions' reactions to these events, whichever streams hold them.
func (Streams) ReactionsForEventIDs(ctx context.Context, s db.Session, eventIDs []string) ([]domain.Reaction, error) {
	if len(eventIDs) == 0 {
		return nil, nil
	}
	rows, err := New(s.Q()).ReactionsForEventIDs(ctx, ReactionsForEventIDsParams{WorkspaceID: s.Workspace().ID(), EventIds: uuids(eventIDs)})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Reaction, 0, len(rows))
	for _, r := range rows {
		out = append(out, toReaction(r.ID, r.TriggerID, r.SubscriptionID, r.StreamID, r.EventID, r.Status, r.Verdict, r.Reason,
			r.Score, r.TaskID, r.DerivedEventIds, r.CreatedAt))
	}
	return out, nil
}
