package router

import (
	"context"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// EventsView is the events-view group: every bus event into the stream_events read model, once.
type EventsView struct{ d Deps }

// NewEventsView builds the events view.
func NewEventsView(d Deps) *EventsView {
	r := New(d)
	return &EventsView{d: r.d}
}

// Handle records the event and announces it to the events pages of its workspace.
func (v *EventsView) Handle(ctx context.Context, m events.IntegrationEvent) error {
	e, err := EventFromBus(m)
	if err != nil {
		return err
	}
	ws, err := wsOf(e)
	if err != nil {
		return fmt.Errorf("%w: %w", events.ErrUnprocessable, err)
	}
	if err := v.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		_, err := store.Streams{}.RecordEvent(ctx, sess, e)
		return err
	}); err != nil {
		return err
	}
	notify(ctx, v.d, NoticeRecorded, e)
	return nil
}

// GiveUp logs an event the view could not write; it is dead-lettered.
func (v *EventsView) GiveUp(ctx context.Context, m events.IntegrationEvent) error {
	v.d.Log.ErrorContext(ctx, "Event could not be written to the events view; dead-lettered", "event_id", m.ID, "type", m.Type)
	return nil
}
