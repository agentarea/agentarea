package service

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	kblob "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// EventLinkTTL is how long an event file's download link lives (EventFileLinks.EXPIRES_IN).
const EventLinkTTL = 3600 * time.Second

// ProcessingTask is a task an event started, with its status.
type ProcessingTask struct {
	ID     string
	Status string
}

// Processing is what the platform did with an event.
type Processing struct {
	Status      string
	Subscribers *int
	Reacted     int
	Skipped     int
	Errors      int
	Tasks       []ProcessingTask
}

func processingOf(e domain.RecordedEvent) Processing {
	return Processing{Status: e.ProcessingStatus(), Subscribers: e.Subscribers, Reacted: e.Reacted, Skipped: e.Skipped,
		Errors: e.Errors, Tasks: []ProcessingTask{}}
}

// FeedItem is an event of the workspace feed: its envelope without body, and its processing.
type FeedItem struct {
	domain.RecordedEvent
	Summary    *string
	Processing Processing
}

// EventView is StreamEventResponse: the envelope, file links and each subscription's outcome.
type EventView struct {
	domain.RecordedEvent
	Summary        *string
	BodyURL        *string
	AttachmentURLs []*string
	Outcomes       []Outcome
	Processing     *Processing
}

// Handler is HandlerResponse: one subscription's reaction, named for its reader.
type Handler struct {
	SubscriptionID  string
	Kind            string
	Name            string
	Verdict         string
	Reason          *string
	TaskID          *string
	TaskStatus      *string
	DerivedEventIDs []string
}

// EventDetail is StreamEventDetailResponse.
type EventDetail struct {
	EventView
	Handlers []Handler
}

// EventPage is StreamEventPage.
type EventPage struct {
	Events     []EventView
	NextAfter  *int64
	NextBefore *int64
}

// FeedPage is WorkspaceEventPage; Facets only on the first page.
type FeedPage struct {
	Events     []FeedItem
	NextBefore *int64
	Facets     *domain.FeedFacets
}

// fileURL is EventFileLinks.url: a presigned link to a workspace file, nil without a path.
func (s *Service) fileURL(ctx context.Context, ws string, path any) (*string, error) {
	p, ok := path.(string)
	if !ok || p == "" {
		return nil, nil
	}
	if s.d.Blob == nil {
		return nil, fmt.Errorf("streams: event file %q needs the artifacts bucket, which is not wired", p)
	}
	scoped, err := kblob.ForWorkspace(s.d.Blob, ws)
	if err != nil {
		return nil, err
	}
	key, err := scoped.Key(p)
	if err != nil {
		return nil, err
	}
	signed, err := s.d.Blob.PresignGet(ctx, key, EventLinkTTL)
	if err != nil {
		return nil, err
	}
	return &signed.URL, nil
}

// eventsWithOutcomes is _events_with_outcomes for events of one stream.
func (s *Service) eventsWithOutcomes(ctx context.Context, sess db.Session, streamID string, evs []domain.RecordedEvent) ([]EventView, error) {
	if len(evs) == 0 {
		return []EventView{}, nil
	}
	subs, err := s.listSubscriptions(ctx, sess, streamID)
	if err != nil {
		return nil, err
	}
	byID := map[string]*domain.Subscription{}
	for i := range subs {
		byID[subs[i].ID] = &subs[i]
	}
	ids := make([]string, len(evs))
	for i, e := range evs {
		ids[i] = e.ID
	}
	rows, err := s.ss.ReactionsForEvents(ctx, sess, uuid.MustParse(streamID), ids)
	if err != nil {
		return nil, err
	}
	summaries, err := s.summaries(ctx, sess, evs)
	if err != nil {
		return nil, err
	}
	byEvent := map[string][]Outcome{}
	for _, r := range rows {
		if r.EventID == nil || r.SubscriptionID == nil {
			continue
		}
		byEvent[*r.EventID] = append(byEvent[*r.EventID], outcomeOf(r, byID[*r.SubscriptionID]))
	}
	out := make([]EventView, 0, len(evs))
	for _, e := range evs {
		v := EventView{RecordedEvent: e, Summary: summaries[e.ID], Outcomes: byEvent[e.ID]}
		if v.Outcomes == nil {
			v.Outcomes = []Outcome{}
		}
		if v.BodyURL, err = s.fileURL(ctx, e.WorkspaceID, e.Data["body_ref"]); err != nil {
			return nil, err
		}
		for _, a := range e.Attachments {
			var u *string
			if a.Stored {
				if u, err = s.fileURL(ctx, e.WorkspaceID, a.Ref); err != nil {
					return nil, err
				}
			}
			v.AttachmentURLs = append(v.AttachmentURLs, u)
		}
		out = append(out, v)
	}
	return out, nil
}

// feedItems is feed_items: each event with the tasks its reactions started and their status.
func (s *Service) feedItems(ctx context.Context, sess db.Session, ws scope.Workspace, evs []domain.RecordedEvent) ([]FeedItem, error) {
	ids := make([]string, len(evs))
	for i, e := range evs {
		ids[i] = e.ID
	}
	rows, err := s.ss.ReactionsForEventIDs(ctx, sess, ids)
	if err != nil {
		return nil, err
	}
	tasksOf := map[string][]string{}
	var all []string
	for _, r := range rows {
		if r.EventID != nil && r.TaskID != nil && r.Verdict != nil && *r.Verdict == domain.VerdictReacted {
			tasksOf[*r.EventID] = append(tasksOf[*r.EventID], *r.TaskID)
			all = append(all, *r.TaskID)
		}
	}
	statuses, err := s.taskStatuses(ctx, ws, all)
	if err != nil {
		return nil, err
	}
	summaries, err := s.summaries(ctx, sess, evs)
	if err != nil {
		return nil, err
	}
	out := make([]FeedItem, 0, len(evs))
	for _, e := range evs {
		p := processingOf(e)
		for _, t := range tasksOf[e.ID] {
			if st, ok := statuses[t]; ok {
				p.Tasks = append(p.Tasks, ProcessingTask{ID: t, Status: st})
			}
		}
		out = append(out, FeedItem{RecordedEvent: e, Summary: summaries[e.ID], Processing: p})
	}
	return out, nil
}

// summaries is each event's one line, read off what it keeps: a platform event's by its body,
// another's by its source's summary template or else its entry's.
func (s *Service) summaries(ctx context.Context, sess db.Session, evs []domain.RecordedEvent) (map[string]*string, error) {
	out := map[string]*string{}
	entries := map[string]*domain.SourceTypeEntry{}
	overrides := map[string]domain.EventOverrides{}
	read := map[string]bool{}
	for _, e := range evs {
		if e.SourceType == nil {
			continue
		}
		if *e.SourceType == domain.PlatformSourceType {
			if body, ok := e.Data["body"].(map[string]any); ok {
				out[e.ID] = PlatformEventSummary(body)
			}
			continue
		}
		entry, known := entries[*e.SourceType]
		if !known {
			got, ok, err := s.SourceTypeEntry(ctx, *e.SourceType)
			if err != nil {
				return nil, err
			}
			if ok {
				entry = &got
			}
			entries[*e.SourceType] = entry
		}
		if entry == nil {
			continue
		}
		if !read[e.StreamID] {
			read[e.StreamID] = true
			sources, err := s.ss.ListSources(ctx, sess, uuid.MustParse(e.StreamID))
			if err != nil {
				return nil, err
			}
			for _, src := range sources {
				if o, err := domain.ParseEventOverrides(src.EventTemplates); err == nil {
					overrides[src.ID] = o
				}
			}
		}
		var o domain.EventOverrides
		if e.SourceID != nil {
			o = overrides[*e.SourceID]
		}
		out[e.ID] = domain.EventSummary(*entry, o, e.Data)
	}
	return out, nil
}

// taskStatuses is TaskRepository.statuses through runs; none without the task port.
func (s *Service) taskStatuses(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error) {
	if len(ids) == 0 || s.d.TaskReads == nil {
		return map[string]string{}, nil
	}
	return s.d.TaskReads.Statuses(ctx, ws, ids)
}

// ListEvents is list_events: oldest first after after; otherwise newest first before before.
func (s *Service) ListEvents(ctx context.Context, streamID string, after, before *int64, limit int) (EventPage, error) {
	if after != nil && before != nil {
		return EventPage{}, domain.Invalid("Pass either after or before, not both")
	}
	c, err := callerOf(ctx)
	if err != nil {
		return EventPage{}, err
	}
	var page EventPage
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		evs, err := s.readEvents(ctx, sess, streamID, after, before, limit)
		if err != nil {
			return err
		}
		if page.Events, err = s.eventsWithOutcomes(ctx, sess, streamID, evs); err != nil {
			return err
		}
		if len(evs) == limit {
			last := evs[len(evs)-1].Sequence
			if after != nil {
				page.NextAfter = &last
			} else {
				page.NextBefore = &last
			}
		}
		return nil
	})
	return page, err
}

func (s *Service) readEvents(ctx context.Context, sess db.Session, streamID string, after, before *int64, limit int) ([]domain.RecordedEvent, error) {
	st, err := s.getStream(ctx, sess, streamID)
	if err != nil {
		return nil, err
	}
	u := uuid.MustParse(st.ID)
	if after != nil {
		return s.ss.EventsAfter(ctx, sess, u, *after, int32(limit)) //nolint:gosec // bounded by the route
	}
	return s.ss.EventsBefore(ctx, sess, u, before, int32(limit)) //nolint:gosec // bounded by the route
}

// GetEvent is get_event: the event at sequence in the stream, with its handlers.
func (s *Service) GetEvent(ctx context.Context, streamID string, sequence int64) (EventDetail, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return EventDetail{}, err
	}
	var out EventDetail
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		after := sequence - 1
		evs, err := s.readEvents(ctx, sess, streamID, &after, nil, 1)
		if err != nil {
			return err
		}
		if len(evs) == 0 || evs[0].Sequence != sequence {
			return domain.Fail(domain.ErrEventNotFound, fmt.Sprintf("Event %d not found in stream", sequence))
		}
		out, err = s.eventDetail(ctx, sess, c, evs[0])
		return err
	})
	return out, err
}

// GetEventByID is get_event_by_id: the event, whichever stream holds it, when the caller reads that stream.
func (s *Service) GetEventByID(ctx context.Context, id string) (EventDetail, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return EventDetail{}, err
	}
	notFound := domain.Fail(domain.ErrEventNotFound, fmt.Sprintf("Event %s not found", id))
	u, err := uuid.Parse(id)
	if err != nil {
		return EventDetail{}, notFound
	}
	var ev domain.RecordedEvent
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		var ok bool
		ev, ok, err = s.ss.EventByID(ctx, sess, u)
		if err == nil && !ok {
			return notFound
		}
		return err
	})
	if err != nil {
		return EventDetail{}, err
	}
	if err := s.perms.Require(ctx, c, "read", "stream", ev.StreamID); err != nil {
		return EventDetail{}, err
	}
	var out EventDetail
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		out, err = s.eventDetail(ctx, sess, c, ev)
		return err
	})
	return out, err
}

// eventDetail is _event_detail.
func (s *Service) eventDetail(ctx context.Context, sess db.Session, c authn.Caller, ev domain.RecordedEvent) (EventDetail, error) {
	views, err := s.eventsWithOutcomes(ctx, sess, ev.StreamID, []domain.RecordedEvent{ev})
	if err != nil {
		return EventDetail{}, err
	}
	items, err := s.feedItems(ctx, sess, c.Workspace, []domain.RecordedEvent{ev})
	if err != nil {
		return EventDetail{}, err
	}
	d := EventDetail{EventView: views[0], Handlers: []Handler{}}
	d.Processing = &items[0].Processing
	subs, err := s.listSubscriptions(ctx, sess, ev.StreamID)
	if err != nil {
		return EventDetail{}, err
	}
	byID := map[string]domain.Subscription{}
	for _, sub := range subs {
		byID[sub.ID] = sub
	}
	var triggerIDs, taskIDs []string
	for _, o := range d.Outcomes {
		if o.TriggerIDOf != nil {
			triggerIDs = append(triggerIDs, *o.TriggerIDOf)
		}
		if o.TaskID != nil {
			taskIDs = append(taskIDs, *o.TaskID)
		}
	}
	triggerNames, err := s.ss.TriggerNames(ctx, sess, triggerIDs)
	if err != nil {
		return EventDetail{}, err
	}
	streams, err := s.ss.ListStreams(ctx, sess, nil, StreamListLimit, 0)
	if err != nil {
		return EventDetail{}, err
	}
	streamNames := map[string]string{}
	for _, st := range streams {
		streamNames[st.ID] = st.Name
	}
	statuses, err := s.taskStatuses(ctx, c.Workspace, taskIDs)
	if err != nil {
		return EventDetail{}, err
	}
	for _, o := range d.Outcomes {
		h := Handler{SubscriptionID: *o.SubscriptionID, Kind: o.SubscriptionKind, Verdict: o.ReactionVerdict(),
			Reason: o.Reason, TaskID: o.TaskID, DerivedEventIDs: o.DerivedEventIDs}
		sub, hasSub := byID[*o.SubscriptionID]
		switch {
		case o.TriggerIDOf != nil:
			h.Name = *o.TriggerIDOf
			if n, ok := triggerNames[*o.TriggerIDOf]; ok {
				h.Name = n
			}
		case hasSub:
			names := make([]string, len(sub.OutputStreamIDs))
			for i, sid := range sub.OutputStreamIDs {
				names[i] = sid
				if n, ok := streamNames[sid]; ok {
					names[i] = n
				}
			}
			h.Name = strings.Join(names, ", ")
		default:
			h.Name = *o.SubscriptionID
		}
		if o.TaskID != nil {
			if st, ok := statuses[*o.TaskID]; ok {
				h.TaskStatus = &st
			}
		}
		d.Handlers = append(d.Handlers, h)
	}
	return d, nil
}

// WorkspaceFeed is list_workspace_events: the events of the streams the caller reads, newest
// first; facets on the first page.
func (s *Service) WorkspaceFeed(ctx context.Context, f domain.FeedFilter, before *int64, limit int) (FeedPage, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return FeedPage{}, err
	}
	var page FeedPage
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		streams, err := s.readableStreams(ctx, sess, c)
		if err != nil {
			return err
		}
		rows, err := s.ss.Feed(ctx, sess, f, streams, before, int32(limit)) //nolint:gosec // bounded by the route
		if err != nil {
			return err
		}
		if before == nil {
			facets, err := s.ss.Facets(ctx, sess, f, streams)
			if err != nil {
				return err
			}
			page.Facets = &facets
		}
		if page.Events, err = s.feedItems(ctx, sess, c.Workspace, rows); err != nil {
			return err
		}
		if len(rows) == limit {
			last := rows[len(rows)-1].Sequence
			page.NextBefore = &last
		}
		return nil
	})
	return page, err
}

// readableStreams is _readable_streams: the ids of the workspace's streams the caller reads.
func (s *Service) readableStreams(ctx context.Context, sess db.Session, c authn.Caller) ([]string, error) {
	ids, err := s.readable(ctx, c)
	if err != nil {
		return nil, err
	}
	rows, err := s.ss.ListStreams(ctx, sess, ids, StreamListLimit, 0)
	if err != nil {
		return nil, err
	}
	out := make([]string, len(rows))
	for i, r := range rows {
		out[i] = r.ID
	}
	return out, nil
}

// feedItem is read_feed_item: one event of the feed if it is in streams and passes the filter.
func (s *Service) feedItem(ctx context.Context, ws scope.Workspace, f domain.FeedFilter, streams []string, eventID string) (*FeedItem, error) {
	var out *FeedItem
	err := s.read(ctx, ws, func(sess db.Session) error {
		f.EventID = &eventID
		rows, err := s.ss.Feed(ctx, sess, f, streams, nil, 1)
		if err != nil || len(rows) == 0 {
			return err
		}
		items, err := s.feedItems(ctx, sess, ws, rows)
		if err != nil {
			return err
		}
		out = &items[0]
		return nil
	})
	return out, err
}
