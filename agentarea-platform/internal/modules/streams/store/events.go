package store

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

const foreignKeyViolation = "23503"

// ToRecorded maps a stream_events row.
func ToRecorded(r StreamEvent) domain.RecordedEvent {
	data, _ := unmarshalMap(r.Data)
	var atts []domain.Attachment
	if len(r.Attachments) > 0 {
		_ = json.Unmarshal(r.Attachments, &atts)
	}
	if atts == nil {
		atts = []domain.Attachment{}
	}
	e := domain.RecordedEvent{
		Event: domain.Event{
			ID: r.EventID.String(), Kind: r.Kind, Source: r.Source, Subject: fromText(r.Subject),
			OccurredAt: r.OccurredAt.Time.UTC(), CorrelationID: fromText(r.CorrelationID), CausationID: fromText(r.CausationID),
			Data: data, StreamID: r.StreamID.String(), WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, EventKey: r.EventKey,
			ReceivedAt: r.ReceivedAt.Time.UTC(), Depth: int(r.Depth), SourceID: fromNullUUID(r.SourceID),
			SourceType: fromText(r.SourceType), SessionKey: fromText(r.SessionKey), Sender: fromText(r.Sender), Attachments: atts,
		},
		Sequence: r.Sequence, RoutedAt: fromTZ(r.RoutedAt), Reacted: int(r.Reacted), Skipped: int(r.Skipped), Errors: int(r.Errors),
	}
	if r.Subscribers.Valid {
		n := int(r.Subscribers.Int32)
		e.Subscribers = &n
	}
	return e
}

func toRecordedList(rows []StreamEvent) []domain.RecordedEvent {
	out := make([]domain.RecordedEvent, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToRecorded(r))
	}
	return out
}

// Routing is what the router writes with an event it records first.
type Routing struct {
	At          time.Time
	Subscribers int
}

// RecordEvent inserts the event once under its stream's insert lock and counts it; false for a repeat
// (by event id alone) or a stream deleted meanwhile.
func (st Streams) RecordEvent(ctx context.Context, s db.Session, e domain.Event) (bool, error) {
	eid, err := uuid.Parse(e.ID)
	if err != nil {
		return false, err
	}
	seen, err := New(s.Q()).EventSeen(ctx, EventSeenParams{WorkspaceID: s.Workspace().ID(), EventID: eid})
	if err != nil || seen {
		return false, err
	}
	return st.insertEvent(ctx, s, e, nil)
}

// MarkRouted records that the router matched subscribers subscriptions, writing the event itself
// when the events view has not yet (true then); the first routing time is kept.
func (st Streams) MarkRouted(ctx context.Context, s db.Session, e domain.Event, subscribers int, at time.Time) (bool, error) {
	inserted, err := st.insertEvent(ctx, s, e, &Routing{At: at, Subscribers: subscribers})
	if err != nil || inserted {
		return inserted, err
	}
	eid, err := uuid.Parse(e.ID)
	if err != nil {
		return false, err
	}
	return false, New(s.Q()).MarkRouted(ctx, MarkRoutedParams{RoutedAt: tz(at), Subscribers: pgtype.Int4{Int32: int32(subscribers), Valid: true},
		WorkspaceID: s.Workspace().ID(), EventID: eid, ReceivedAt: tz(e.ReceivedAt)})
}

// MarkReactions writes the event's reaction tally.
func (Streams) MarkReactions(ctx context.Context, s db.Session, e domain.Event, reacted, skipped, errs int) error {
	eid, err := uuid.Parse(e.ID)
	if err != nil {
		return err
	}
	return New(s.Q()).MarkReactions(ctx, MarkReactionsParams{Reacted: int32(reacted), Skipped: int32(skipped), Errors: int32(errs),
		WorkspaceID: s.Workspace().ID(), EventID: eid, ReceivedAt: tz(e.ReceivedAt)})
}

func (Streams) insertEvent(ctx context.Context, s db.Session, e domain.Event, routing *Routing) (bool, error) {
	if e.WorkspaceID != s.Workspace().ID() {
		return false, errors.New("event " + e.ID + " belongs to workspace " + e.WorkspaceID + ", not " + s.Workspace().ID())
	}
	stream, err := uuid.Parse(e.StreamID)
	if err != nil {
		return false, err
	}
	eid, err := uuid.Parse(e.ID)
	if err != nil {
		return false, err
	}
	srcID, err := nullUUID(e.SourceID)
	if err != nil {
		return false, err
	}
	data, err := json.Marshal(e.Data)
	if err != nil {
		return false, err
	}
	atts := e.Attachments
	if atts == nil {
		atts = []domain.Attachment{}
	}
	attJSON, err := json.Marshal(atts)
	if err != nil {
		return false, err
	}
	q := New(s.Q())
	if err := q.StreamInsertLock(ctx, e.StreamID); err != nil {
		return false, err
	}
	p := InsertEventParams{ReceivedAt: tz(e.ReceivedAt), StreamID: stream, EventID: eid, EventKey: e.EventKey, Kind: e.Kind,
		Source: e.Source, Subject: text(e.Subject), OccurredAt: tz(e.OccurredAt), CorrelationID: text(e.CorrelationID),
		CausationID: text(e.CausationID), SourceID: srcID, SourceType: text(e.SourceType), SessionKey: text(e.SessionKey),
		Sender: text(e.Sender), Depth: int32(e.Depth), Data: data, Attachments: attJSON, WorkspaceID: e.WorkspaceID,
		CreatedBy: e.CreatedBy}
	if routing != nil {
		p.RoutedAt = tz(routing.At)
		p.Subscribers = pgtype.Int4{Int32: int32(routing.Subscribers), Valid: true}
	}
	inserted := false
	err = savepoint(ctx, s, func(ctx context.Context, sp db.Querier) error {
		qq := New(sp)
		if _, err := qq.InsertEvent(ctx, p); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return nil
			}
			return err
		}
		inserted = true
		srcType := ""
		if e.SourceType != nil {
			srcType = *e.SourceType
		}
		day := e.ReceivedAt.UTC()
		return qq.CountEvent(ctx, CountEventParams{WorkspaceID: e.WorkspaceID, CreatedBy: e.CreatedBy, StreamID: stream,
			Day: pgtype.Date{Time: time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC), Valid: true}, SourceType: srcType})
	})
	var pg *pgconn.PgError
	if errors.As(err, &pg) && pg.Code == foreignKeyViolation {
		return false, nil
	}
	return inserted && err == nil, err
}

// EventByID returns the workspace's event with id, whichever stream holds it.
func (Streams) EventByID(ctx context.Context, s db.Session, id uuid.UUID) (domain.RecordedEvent, bool, error) {
	r, err := New(s.Q()).EventByID(ctx, EventByIDParams{WorkspaceID: s.Workspace().ID(), EventID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.RecordedEvent{}, false, nil
	}
	if err != nil {
		return domain.RecordedEvent{}, false, err
	}
	return ToRecorded(r), true, nil
}

// EventsAfter reads the stream oldest first past sequence after.
func (Streams) EventsAfter(ctx context.Context, s db.Session, streamID uuid.UUID, after int64, limit int32) ([]domain.RecordedEvent, error) {
	rows, err := New(s.Q()).EventsAfter(ctx, EventsAfterParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID, After: after, Lim: limit})
	return toRecordedList(rows), err
}

// EventsBefore reads the stream newest first before sequence before (nil: from the newest).
func (Streams) EventsBefore(ctx context.Context, s db.Session, streamID uuid.UUID, before *int64, limit int32) ([]domain.RecordedEvent, error) {
	b := pgtype.Int8{}
	if before != nil {
		b = pgtype.Int8{Int64: *before, Valid: true}
	}
	rows, err := New(s.Q()).EventsBefore(ctx, EventsBeforeParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID, Before: b, Lim: limit})
	return toRecordedList(rows), err
}

// EventsSince reads the stream oldest first, received at or after since and past after.
func (Streams) EventsSince(ctx context.Context, s db.Session, streamID uuid.UUID, since time.Time, after int64, limit int32) ([]domain.RecordedEvent, error) {
	rows, err := New(s.Q()).EventsSince(ctx, EventsSinceParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID, Since: tz(since), After: after, Lim: limit})
	return toRecordedList(rows), err
}

// HeadSequence is the stream's newest sequence, 0 when empty.
func (Streams) HeadSequence(ctx context.Context, s db.Session, streamID uuid.UUID) (int64, error) {
	return New(s.Q()).HeadSequence(ctx, HeadSequenceParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID})
}

func feedArgs(f domain.FeedFilter) (stream uuid.NullUUID, src, exact, prefix, sender, session, result pgtype.Text, since, until pgtype.Timestamptz, event uuid.NullUUID) {
	if f.StreamID != nil {
		if u, err := uuid.Parse(*f.StreamID); err == nil {
			stream = uuid.NullUUID{UUID: u, Valid: true}
		}
	}
	src = text(f.SourceType)
	if k := f.ExactKind(); k != "" {
		exact = pgtype.Text{String: k, Valid: true}
	}
	if p := f.KindPrefix(); p != "" {
		prefix = pgtype.Text{String: p, Valid: true}
	}
	sender, session, result = text(f.Sender), text(f.SessionKey), text(f.Result)
	since, until = nullTZ(f.Since), nullTZ(f.Until)
	if f.EventID != nil {
		if u, err := uuid.Parse(*f.EventID); err == nil {
			event = uuid.NullUUID{UUID: u, Valid: true}
		}
	}
	return
}

// Feed reads the workspace feed of streams newest first, before sequence before when set.
func (Streams) Feed(ctx context.Context, s db.Session, f domain.FeedFilter, streams []string, before *int64, limit int32) ([]domain.RecordedEvent, error) {
	stream, src, exact, prefix, sender, session, result, since, until, event := feedArgs(f)
	b := pgtype.Int8{}
	if before != nil {
		b = pgtype.Int8{Int64: *before, Valid: true}
	}
	rows, err := New(s.Q()).FeedEvents(ctx, FeedEventsParams{WorkspaceID: s.Workspace().ID(), StreamIds: uuids(streams),
		StreamID: stream, SourceType: src, Platform: f.Platform, ExactKind: exact, KindPrefix: prefix, Sender: sender,
		SessionKey: session, Result: result, Since: since, Until: until, EventID: event, Before: b, Lim: limit})
	return toRecordedList(rows), err
}

// Facets counts the feed per stream and per source type: from the rollup when only stream and
// source type filter it, otherwise from a scan stopped after domain.FacetCap matching events.
func (Streams) Facets(ctx context.Context, s db.Session, f domain.FeedFilter, streams []string) (domain.FeedFacets, error) {
	out := domain.FeedFacets{Streams: map[string]int64{}, SourceTypes: map[string]int64{}}
	q := New(s.Q())
	stream, src, exact, prefix, sender, session, result, since, until, event := feedArgs(f)
	if !f.HasOtherConditions() {
		byStream, err := q.FacetsByStream(ctx, FacetsByStreamParams{WorkspaceID: s.Workspace().ID(), StreamIds: uuids(streams), SourceType: src})
		if err != nil {
			return out, err
		}
		for _, r := range byStream {
			out.Streams[r.StreamID.String()] = r.N
		}
		bySource, err := q.FacetsBySourceType(ctx, FacetsBySourceTypeParams{WorkspaceID: s.Workspace().ID(), StreamIds: uuids(streams), StreamID: stream})
		if err != nil {
			return out, err
		}
		for _, r := range bySource {
			out.SourceTypes[r.SourceType] = r.N
		}
		return out, nil
	}
	rows, err := q.CappedFacets(ctx, CappedFacetsParams{WorkspaceID: s.Workspace().ID(), StreamIds: uuids(streams),
		Either: stream.Valid && src.Valid, StreamID: stream, SourceType: src, ExactKind: exact, KindPrefix: prefix,
		Sender: sender, SessionKey: session, Result: result, Since: since, Until: until, EventID: event, Lim: domain.FacetCap + 1})
	if err != nil {
		return out, err
	}
	var total int64
	for _, r := range rows {
		total += r.N
		if f.SourceType == nil || (r.SourceType.Valid && r.SourceType.String == *f.SourceType) {
			out.Streams[r.StreamID.String()] += r.N
		}
		if r.SourceType.Valid && (f.StreamID == nil || r.StreamID.String() == *f.StreamID) {
			out.SourceTypes[r.SourceType.String] += r.N
		}
	}
	out.Capped = total > domain.FacetCap
	return out, nil
}

// LastReceivedByStream is the last event time of each stream that has events.
func (Streams) LastReceivedByStream(ctx context.Context, s db.Session, streams []string) (map[string]time.Time, error) {
	out := map[string]time.Time{}
	if len(streams) == 0 {
		return out, nil
	}
	rows, err := New(s.Q()).LastReceivedByStream(ctx, LastReceivedByStreamParams{WorkspaceID: s.Workspace().ID(), StreamIds: uuids(streams)})
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		out[r.StreamID.String()] = r.LastReceivedAt.Time.UTC()
	}
	return out, nil
}

func toReaction(id uuid.UUID, trig, sub, stream, event uuid.NullUUID, status string, verdict, reason pgtype.Text,
	score pgtype.Float8, task uuid.NullUUID, derived []byte, at pgtype.Timestamp) domain.Reaction {
	r := domain.Reaction{ID: id.String(), TriggerID: fromNullUUID(trig), SubscriptionID: fromNullUUID(sub),
		StreamID: fromNullUUID(stream), EventID: fromNullUUID(event), Status: status, Verdict: fromText(verdict),
		Reason: fromText(reason), TaskID: fromNullUUID(task), DerivedEventIDs: strList(derived), CreatedAt: fromNaive(at)}
	if score.Valid {
		v := score.Float64
		r.Score = &v
	}
	return r
}

// ReactionsForEvents lists the reactions to these events of the stream, oldest first.
func (Streams) ReactionsForEvents(ctx context.Context, s db.Session, streamID uuid.UUID, eventIDs []string) ([]domain.Reaction, error) {
	if len(eventIDs) == 0 {
		return nil, nil
	}
	rows, err := New(s.Q()).ReactionsForEvents(ctx, ReactionsForEventsParams{WorkspaceID: s.Workspace().ID(),
		StreamID: uuid.NullUUID{UUID: streamID, Valid: true}, EventIds: uuids(eventIDs)})
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

// ReactionsForSubscription lists the subscription's newest reactions.
func (Streams) ReactionsForSubscription(ctx context.Context, s db.Session, subID uuid.UUID, limit int32) ([]domain.Reaction, error) {
	rows, err := New(s.Q()).ReactionsForSubscription(ctx, ReactionsForSubscriptionParams{WorkspaceID: s.Workspace().ID(),
		SubscriptionID: uuid.NullUUID{UUID: subID, Valid: true}, Lim: limit})
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

// NewReaction is one subscription's reaction to one event, to record.
type NewReaction struct {
	TriggerID       *string
	SubscriptionID  string
	StreamID        string
	EventID         string
	Status          string
	Verdict         string
	Reason          *string
	Score           *float64
	TaskID          *string
	WorkflowID      *string
	FiredBy         *string
	ErrorMessage    *string
	ExecutionTime   time.Duration
	TriggerData     map[string]any
	DerivedEventIDs []string
	CorrelationID   *string
	CausationID     *string
	CreatedBy       string
}

// RecordReaction writes the reaction once per (subscription, event); false when one exists.
func (Streams) RecordReaction(ctx context.Context, s db.Session, r NewReaction, now time.Time) (bool, error) {
	trig, err := nullUUID(r.TriggerID)
	if err != nil {
		return false, err
	}
	task, err := nullUUID(r.TaskID)
	if err != nil {
		return false, err
	}
	sub, err := uuid.Parse(r.SubscriptionID)
	if err != nil {
		return false, err
	}
	stream, err := uuid.Parse(r.StreamID)
	if err != nil {
		return false, err
	}
	event, err := uuid.Parse(r.EventID)
	if err != nil {
		return false, err
	}
	data := r.TriggerData
	if data == nil {
		data = map[string]any{}
	}
	td, err := json.Marshal(data)
	if err != nil {
		return false, err
	}
	derived := r.DerivedEventIDs
	if derived == nil {
		derived = []string{}
	}
	dj, err := json.Marshal(derived)
	if err != nil {
		return false, err
	}
	score := pgtype.Float8{}
	if r.Score != nil {
		score = pgtype.Float8{Float64: *r.Score, Valid: true}
	}
	_, err = New(s.Q()).InsertReaction(ctx, InsertReactionParams{ID: uuid.New(), TriggerID: trig, Now: naive(now), Status: r.Status,
		TaskID: task, ExecutionTimeMs: int32(r.ExecutionTime / time.Millisecond), ErrorMessage: text(r.ErrorMessage), TriggerData: td,
		WorkflowID: text(r.WorkflowID), WorkspaceID: s.Workspace().ID(), CreatedBy: r.CreatedBy, FiredBy: text(r.FiredBy),
		SubscriptionID: uuid.NullUUID{UUID: sub, Valid: true}, StreamID: uuid.NullUUID{UUID: stream, Valid: true},
		EventID: uuid.NullUUID{UUID: event, Valid: true}, Verdict: pgtype.Text{String: r.Verdict, Valid: true}, Reason: text(r.Reason),
		Score: score, DerivedEventIds: dj, CorrelationID: text(r.CorrelationID), CausationID: text(r.CausationID)})
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

// ReactionExists reports whether the subscription already reacted to the event.
func (Streams) ReactionExists(ctx context.Context, s db.Session, subID, eventID uuid.UUID) (bool, error) {
	return New(s.Q()).ReactionExists(ctx, ReactionExistsParams{SubscriptionID: uuid.NullUUID{UUID: subID, Valid: true},
		EventID: uuid.NullUUID{UUID: eventID, Valid: true}})
}

// ReactionTally counts the event's recorded reactions: all, skipped, errors.
func (Streams) ReactionTally(ctx context.Context, s db.Session, eventID uuid.UUID) (int, int, int, error) {
	r, err := New(s.Q()).ReactionTally(ctx, ReactionTallyParams{WorkspaceID: s.Workspace().ID(), EventID: uuid.NullUUID{UUID: eventID, Valid: true}})
	return int(r.Reacted), int(r.Skipped), int(r.Errors), err
}

// savepoint runs fn so that its failure leaves the session's transaction usable.
func savepoint(ctx context.Context, s db.Session, fn func(context.Context, db.Querier) error) error {
	if !s.InTx() {
		return fn(ctx, s.Q())
	}
	if _, err := s.Q().Exec(ctx, "SAVEPOINT streams_insert"); err != nil {
		return err
	}
	if err := fn(ctx, s.Q()); err != nil {
		if _, rerr := s.Q().Exec(ctx, "ROLLBACK TO SAVEPOINT streams_insert"); rerr != nil {
			return errors.Join(err, rerr)
		}
		return err
	}
	_, err := s.Q().Exec(ctx, "RELEASE SAVEPOINT streams_insert")
	return err
}
