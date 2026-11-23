package store

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// Streams reads and writes streams, their sources, subscriptions, events and
// reactions inside the session's workspace.
type Streams struct{}

func toStream(id uuid.UUID, ws, by string, at pgtype.Timestamp, name, desc, kind string) domain.Stream {
	return domain.Stream{ID: id.String(), WorkspaceID: ws, CreatedBy: by, CreatedAt: fromNaive(at), Name: name,
		Description: desc, Kind: kind}
}

func uuids(ids []string) []uuid.UUID {
	out := make([]uuid.UUID, 0, len(ids))
	for _, s := range ids {
		if u, err := uuid.Parse(s); err == nil {
			out = append(out, u)
		}
	}
	return out
}

func tz(t time.Time) pgtype.Timestamptz { return pgtype.Timestamptz{Time: t.UTC(), Valid: true} }

func nullTZ(p *time.Time) pgtype.Timestamptz {
	if p == nil {
		return pgtype.Timestamptz{}
	}
	return tz(*p)
}

func fromTZ(t pgtype.Timestamptz) *time.Time {
	if !t.Valid {
		return nil
	}
	v := t.Time.UTC()
	return &v
}

func strList(b []byte) []string {
	var raw []any
	if len(b) == 0 || json.Unmarshal(b, &raw) != nil {
		return []string{}
	}
	out := make([]string, 0, len(raw))
	for _, v := range raw {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func mapOrNil(b []byte) map[string]any {
	if len(b) == 0 || string(b) == "null" {
		return nil
	}
	var m map[string]any
	if json.Unmarshal(b, &m) != nil {
		return nil
	}
	return m
}

// InsertStream writes a stream; domain.ErrNameTaken when the workspace has the name.
func (Streams) InsertStream(ctx context.Context, s db.Session, st domain.Stream, now time.Time) (domain.Stream, error) {
	id, err := uuid.Parse(st.ID)
	if err != nil {
		return domain.Stream{}, err
	}
	r, err := New(s.Q()).InsertStream(ctx, InsertStreamParams{ID: id, WorkspaceID: s.Workspace().ID(), CreatedBy: st.CreatedBy,
		Now: naive(now), Name: st.Name, Description: st.Description, Kind: st.Kind})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Stream{}, domain.NameTaken(st.Name)
	}
	if err != nil {
		return domain.Stream{}, err
	}
	return toStream(r.ID, r.WorkspaceID, r.CreatedBy, r.CreatedAt, r.Name, r.Description, r.Kind), nil
}

// GetStream returns the stream, false when the workspace has none with id.
func (Streams) GetStream(ctx context.Context, s db.Session, id uuid.UUID) (domain.Stream, bool, error) {
	r, err := New(s.Q()).GetStream(ctx, GetStreamParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Stream{}, false, nil
	}
	if err != nil {
		return domain.Stream{}, false, err
	}
	st := toStream(r.ID, r.WorkspaceID, r.CreatedBy, r.CreatedAt, r.Name, r.Description, r.Kind)
	st.SourceTypes = r.SourceTypes
	return st, true, nil
}

// GetStreamByName returns the stream named name, false when none.
func (Streams) GetStreamByName(ctx context.Context, s db.Session, name string) (domain.Stream, bool, error) {
	r, err := New(s.Q()).GetStreamByName(ctx, GetStreamByNameParams{WorkspaceID: s.Workspace().ID(), Name: name})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Stream{}, false, nil
	}
	if err != nil {
		return domain.Stream{}, false, err
	}
	return toStream(r.ID, r.WorkspaceID, r.CreatedBy, r.CreatedAt, r.Name, r.Description, r.Kind), true, nil
}

// GetPlatformStream returns the workspace's platform stream, false before it exists.
func (Streams) GetPlatformStream(ctx context.Context, s db.Session) (domain.Stream, bool, error) {
	r, err := New(s.Q()).GetPlatformStream(ctx, s.Workspace().ID())
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Stream{}, false, nil
	}
	if err != nil {
		return domain.Stream{}, false, err
	}
	return toStream(r.ID, r.WorkspaceID, r.CreatedBy, r.CreatedAt, r.Name, r.Description, r.Kind), true, nil
}

// ListStreams is a page of the workspace's streams; ids, when not nil, narrows to them.
func (Streams) ListStreams(ctx context.Context, s db.Session, ids []string, limit, offset int32) ([]domain.Stream, error) {
	rows, err := New(s.Q()).ListStreams(ctx, ListStreamsParams{WorkspaceID: s.Workspace().ID(), FilterIds: ids != nil,
		Ids: uuids(ids), Lim: limit, Off: offset})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Stream, 0, len(rows))
	for _, r := range rows {
		st := toStream(r.ID, r.WorkspaceID, r.CreatedBy, r.CreatedAt, r.Name, r.Description, r.Kind)
		st.SourceTypes = r.SourceTypes
		out = append(out, st)
	}
	return out, nil
}

// LockForDelete reads the stream row locked until commit.
func (Streams) LockForDelete(ctx context.Context, s db.Session, id uuid.UUID) (domain.Stream, bool, error) {
	r, err := New(s.Q()).LockStreamForDelete(ctx, LockStreamForDeleteParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Stream{}, false, nil
	}
	if err != nil {
		return domain.Stream{}, false, err
	}
	return toStream(r.ID, r.WorkspaceID, r.CreatedBy, r.CreatedAt, r.Name, r.Description, r.Kind), true, nil
}

// LockExisting reports which of ids exist here, each kept from deletion until commit.
func (Streams) LockExisting(ctx context.Context, s db.Session, ids []string) (map[string]bool, error) {
	out := map[string]bool{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := New(s.Q()).LockExistingStreams(ctx, LockExistingStreamsParams{WorkspaceID: s.Workspace().ID(), Ids: uuids(ids)})
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		out[r.String()] = true
	}
	return out, nil
}

// StreamNames maps each id that exists here to its name.
func (Streams) StreamNames(ctx context.Context, s db.Session, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := New(s.Q()).StreamNames(ctx, StreamNamesParams{WorkspaceID: s.Workspace().ID(), Ids: uuids(ids)})
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		out[r.ID.String()] = r.Name
	}
	return out, nil
}

// SetDescription writes the stream's description; false when there is no such stream.
func (Streams) SetDescription(ctx context.Context, s db.Session, id uuid.UUID, description string, now time.Time) (bool, error) {
	n, err := New(s.Q()).SetStreamDescription(ctx, SetStreamDescriptionParams{WorkspaceID: s.Workspace().ID(), ID: id, Description: description,
		Now: naive(now)})
	return n == 1, err
}

// DeleteStream removes the stream; its sources, subscriptions and events go with it.
func (Streams) DeleteStream(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteStream(ctx, DeleteStreamParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n == 1, err
}

// ToSource maps a stream_sources row.
func ToSource(r StreamSource) domain.Source {
	return domain.Source{
		ID: r.ID.String(), WorkspaceID: r.WorkspaceID, StreamID: r.StreamID.String(), Kind: r.Kind,
		WebhookID: fromText(r.WebhookID), SourceType: fromText(r.WebhookType), WebhookConfig: mapOrNil(r.WebhookConfig),
		CredentialKey: fromNullUUID(r.CredentialKey), EventTemplates: mapOrNil(r.EventTemplates),
		PollCursor: fromText(r.PollCursor), PolledAt: fromTZ(r.PolledAt), PollError: fromText(r.PollError),
		RegisteredURL: fromText(r.RegisteredUrl), SubscriptionID: fromText(r.SubscriptionID),
		RefreshBefore: fromTZ(r.RefreshBefore), Senders: mapOrNil(r.Senders), CreatedBy: r.CreatedBy,
		CreatedAt: fromNaive(r.CreatedAt),
	}
}

// InsertSource writes a source; its credential key is its own id unless set.
func (Streams) InsertSource(ctx context.Context, s db.Session, src domain.Source, now time.Time) (domain.Source, error) {
	id, err := uuid.Parse(src.ID)
	if err != nil {
		return domain.Source{}, err
	}
	stream, err := uuid.Parse(src.StreamID)
	if err != nil {
		return domain.Source{}, err
	}
	cred, err := nullUUID(src.CredentialKey)
	if err != nil {
		return domain.Source{}, err
	}
	cfg, err := marshal(src.WebhookConfig)
	if err != nil {
		return domain.Source{}, err
	}
	tmpl, err := marshal(src.EventTemplates)
	if err != nil {
		return domain.Source{}, err
	}
	var senders []byte
	if src.Senders != nil {
		if senders, err = json.Marshal(src.Senders); err != nil {
			return domain.Source{}, err
		}
	}
	r, err := New(s.Q()).InsertSource(ctx, InsertSourceParams{ID: id, WorkspaceID: s.Workspace().ID(), CreatedBy: src.CreatedBy,
		Now: naive(now), StreamID: stream, Kind: src.Kind, WebhookID: text(src.WebhookID), WebhookType: text(src.SourceType),
		WebhookConfig: cfg, CredentialKey: cred, EventTemplates: tmpl, Senders: senders})
	if err != nil {
		return domain.Source{}, err
	}
	return ToSource(r), nil
}

// ListSources lists the stream's sources.
func (Streams) ListSources(ctx context.Context, s db.Session, streamID uuid.UUID) ([]domain.Source, error) {
	rows, err := New(s.Q()).ListSources(ctx, ListSourcesParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Source, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToSource(r))
	}
	return out, nil
}

// GetSource returns the stream's source, false when none.
func (Streams) GetSource(ctx context.Context, s db.Session, streamID, id uuid.UUID) (domain.Source, bool, error) {
	r, err := New(s.Q()).GetSourceInStream(ctx, GetSourceInStreamParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID, ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Source{}, false, nil
	}
	if err != nil {
		return domain.Source{}, false, err
	}
	return ToSource(r), true, nil
}

// SetSenders writes the source's senders record; false when the source is gone.
func (Streams) SetSenders(ctx context.Context, s db.Session, streamID, id uuid.UUID, senders map[string]any, now time.Time) (domain.Source, bool, error) {
	b, err := marshal(senders)
	if err != nil {
		return domain.Source{}, false, err
	}
	r, err := New(s.Q()).SetSourceSenders(ctx, SetSourceSendersParams{Senders: b, Now: naive(now), WorkspaceID: s.Workspace().ID(),
		StreamID: streamID, ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Source{}, false, nil
	}
	if err != nil {
		return domain.Source{}, false, err
	}
	return ToSource(r), true, nil
}

// DeleteSource removes the source; its events stay.
func (Streams) DeleteSource(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteSource(ctx, DeleteSourceParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n == 1, err
}

// FindWebhookSource finds a webhook source by its public id in any workspace.
func (Streams) FindWebhookSource(ctx context.Context, q db.Querier, webhookID string) (domain.Source, bool, error) {
	r, err := New(q).FindWebhookSource(ctx, pgtype.Text{String: webhookID, Valid: true})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Source{}, false, nil
	}
	if err != nil {
		return domain.Source{}, false, err
	}
	return ToSource(r), true, nil
}

// EndSourceSubscription clears a source's provider registration and records why (the "ended" signal).
func (Streams) EndSourceSubscription(ctx context.Context, q db.Querier, id uuid.UUID, reason string, now time.Time) error {
	_, err := New(q).EndSourceSubscription(ctx, EndSourceSubscriptionParams{PollError: pgtype.Text{String: reason, Valid: true},
		Now: naive(now), ID: id})
	return err
}

// ToSubscription maps a stream_subscriptions row.
func ToSubscription(r StreamSubscription) domain.Subscription {
	f, _ := unmarshalMap(r.Filter)
	return domain.Subscription{
		ID: r.ID.String(), WorkspaceID: r.WorkspaceID, StreamID: r.StreamID.String(), Kind: r.Kind,
		TriggerID: fromNullUUID(r.TriggerID), Filter: f, OutputStreamIDs: strList(r.OutputStreamIds), Status: r.Status,
		StartedAt: r.StartedAt.Time.UTC(), ExternalID: fromText(r.ExternalID), Subscriber: fromText(r.Subscriber),
		CallbackURL: fromText(r.CallbackUrl), SecretName: fromText(r.SecretName), ExpiresAt: fromTZ(r.ExpiresAt),
		VerifiedAt: fromTZ(r.VerifiedAt), LastDeliveryAt: fromTZ(r.LastDeliveryAt), LastError: fromText(r.LastError),
		FailedSince: fromTZ(r.FailedSince), Code: fromText(r.Code), CreatedBy: r.CreatedBy, CreatedAt: fromNaive(r.CreatedAt),
	}
}

// InsertSubscription writes a trigger, forward or processor subscription.
func (Streams) InsertSubscription(ctx context.Context, s db.Session, sub domain.Subscription, now time.Time) (domain.Subscription, error) {
	id, err := uuid.Parse(sub.ID)
	if err != nil {
		return domain.Subscription{}, err
	}
	stream, err := uuid.Parse(sub.StreamID)
	if err != nil {
		return domain.Subscription{}, err
	}
	trig, err := nullUUID(sub.TriggerID)
	if err != nil {
		return domain.Subscription{}, err
	}
	f, err := marshal(sub.Filter)
	if err != nil {
		return domain.Subscription{}, err
	}
	outs := sub.OutputStreamIDs
	if outs == nil {
		outs = []string{}
	}
	o, err := json.Marshal(outs)
	if err != nil {
		return domain.Subscription{}, err
	}
	r, err := New(s.Q()).InsertSubscription(ctx, InsertSubscriptionParams{ID: id, WorkspaceID: s.Workspace().ID(), CreatedBy: sub.CreatedBy,
		Now: naive(now), StreamID: stream, Kind: sub.Kind, TriggerID: trig, Filter: f, OutputStreamIds: o, Status: sub.Status,
		StartedAt: tz(now), Code: text(sub.Code)})
	if err != nil {
		return domain.Subscription{}, err
	}
	return ToSubscription(r), nil
}

// ListSubscriptions lists the stream's subscriptions, oldest first.
func (Streams) ListSubscriptions(ctx context.Context, s db.Session, streamID uuid.UUID) ([]domain.Subscription, error) {
	rows, err := New(s.Q()).ListSubscriptions(ctx, ListSubscriptionsParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Subscription, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToSubscription(r))
	}
	return out, nil
}

// GetSubscription returns the stream's subscription, false when none.
func (Streams) GetSubscription(ctx context.Context, s db.Session, streamID, id uuid.UUID) (domain.Subscription, bool, error) {
	r, err := New(s.Q()).GetSubscriptionInStream(ctx, GetSubscriptionInStreamParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID, ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Subscription{}, false, nil
	}
	if err != nil {
		return domain.Subscription{}, false, err
	}
	return ToSubscription(r), true, nil
}

// GetActiveSubscription returns the subscription while it exists, is active and has not expired.
func (Streams) GetActiveSubscription(ctx context.Context, s db.Session, id uuid.UUID) (domain.Subscription, bool, error) {
	r, err := New(s.Q()).GetActiveSubscription(ctx, GetActiveSubscriptionParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Subscription{}, false, nil
	}
	if err != nil {
		return domain.Subscription{}, false, err
	}
	return ToSubscription(r), true, nil
}

// UpdateProcessor writes a processor's code, outputs and filter.
func (Streams) UpdateProcessor(ctx context.Context, s db.Session, sub domain.Subscription, now time.Time) (domain.Subscription, error) {
	id, err := uuid.Parse(sub.ID)
	if err != nil {
		return domain.Subscription{}, err
	}
	f, err := marshal(sub.Filter)
	if err != nil {
		return domain.Subscription{}, err
	}
	o, err := json.Marshal(sub.OutputStreamIDs)
	if err != nil {
		return domain.Subscription{}, err
	}
	r, err := New(s.Q()).UpdateProcessor(ctx, UpdateProcessorParams{Code: text(sub.Code), OutputStreamIds: o, Filter: f,
		Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id})
	if err != nil {
		return domain.Subscription{}, err
	}
	return ToSubscription(r), nil
}

// DeleteSubscription removes a subscription; its reactions cascade.
func (Streams) DeleteSubscription(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteSubscription(ctx, DeleteSubscriptionParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n == 1, err
}

// TriggerIDsOnStream lists the triggers subscribed to the stream.
func (Streams) TriggerIDsOnStream(ctx context.Context, s db.Session, streamID uuid.UUID) ([]string, error) {
	rows, err := New(s.Q()).TriggerIDsOnStream(ctx, TriggerIDsOnStreamParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID})
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(rows))
	for _, r := range rows {
		if r.Valid {
			out = append(out, r.UUID.String())
		}
	}
	return out, nil
}

// WritersInto lists the forwards and processors that write into the stream.
func (Streams) WritersInto(ctx context.Context, s db.Session, streamID uuid.UUID) ([]domain.Subscription, error) {
	rows, err := New(s.Q()).WritersInto(ctx, WritersIntoParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID.String()})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Subscription, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToSubscription(r))
	}
	return out, nil
}

// ExternalOnStream lists the stream's external subscribers.
func (Streams) ExternalOnStream(ctx context.Context, s db.Session, streamID uuid.UUID) ([]domain.Subscription, error) {
	rows, err := New(s.Q()).ExternalSubscriptionsOnStream(ctx, ExternalSubscriptionsOnStreamParams{WorkspaceID: s.Workspace().ID(), StreamID: streamID})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Subscription, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToSubscription(r))
	}
	return out, nil
}

// TriggerNames maps each trigger id that exists here to its name.
func (Streams) TriggerNames(ctx context.Context, s db.Session, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := New(s.Q()).TriggerNames(ctx, TriggerNamesParams{WorkspaceID: s.Workspace().ID(), Ids: uuids(ids)})
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		out[r.ID.String()] = r.Name
	}
	return out, nil
}
