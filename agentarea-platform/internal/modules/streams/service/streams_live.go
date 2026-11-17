package service

import (
	"context"
	"errors"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// Live notice kinds (NoticeKind).
const (
	NoticeRecorded   = "event.recorded"
	NoticeProcessing = "event.processing"
)

// LiveQueueLimit is the notices a page may fall behind before its stream ends (QUEUE_LIMIT).
const LiveQueueLimit = 1000

// ErrLiveUnavailable is the live feed without the broker's pub/sub wired.
var ErrLiveUnavailable = errors.New("streams: the events feed reads the broker's live channels, which are not wired")

// Notice is an EventNotice.
type Notice struct {
	Kind     string
	EventID  string
	StreamID string
}

// LiveFrame is one SSE event of the live feed: event.recorded carries the item, event.processing
// the item's processing.
type LiveFrame struct {
	Kind string
	Item FeedItem
}

// noticeHub is EventNoticesHub: one pub/sub connection shared by the open pages.
type noticeHub struct {
	broker events.Broker
	log    interface {
		Error(msg string, args ...any)
		Warn(msg string, args ...any)
	}
	mu     sync.Mutex
	live   events.LiveChannels
	queues map[string]map[chan Notice]bool
}

func (h *noticeHub) subscribe(ctx context.Context, ws string) (chan Notice, func(), error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.live == nil {
		live, err := h.broker.OpenLive(context.WithoutCancel(ctx))
		if err != nil {
			return nil, nil, err
		}
		h.live = live
		go h.run(live)
	}
	q := make(chan Notice, LiveQueueLimit)
	first := h.queues[ws] == nil
	if first {
		h.queues[ws] = map[chan Notice]bool{}
	}
	h.queues[ws][q] = true
	if first {
		if err := h.live.Subscribe(ctx, events.StreamsLiveChannel(ws)); err != nil {
			delete(h.queues, ws)
			return nil, nil, err
		}
	}
	return q, func() {
		h.mu.Lock()
		defer h.mu.Unlock()
		qs := h.queues[ws]
		if !qs[q] {
			return
		}
		delete(qs, q)
		if len(qs) == 0 {
			delete(h.queues, ws)
			if err := h.live.Unsubscribe(context.WithoutCancel(ctx), events.StreamsLiveChannel(ws)); err != nil {
				h.log.Error("Failed to leave a workspace's live events channel", "workspace_id", ws, "error", err.Error())
			}
		}
	}, nil
}

func (h *noticeHub) run(live events.LiveChannels) {
	ctx := context.Background()
	prefix := events.StreamsLive + "."
	for {
		channel, fields, ok, err := live.Next(ctx, time.Second)
		if err != nil {
			h.log.Error("Live event notices failed; retrying", "error", err.Error())
			time.Sleep(time.Second)
			continue
		}
		if !ok {
			continue
		}
		n, err := parseNotice(fields)
		if err != nil {
			h.log.Error("Unreadable event notice; skipped", "channel", channel, "error", err.Error())
			continue
		}
		h.dispatch(strings.TrimPrefix(channel, prefix), n)
	}
}

func parseNotice(fields map[string]string) (Notice, error) {
	kind := fields["type"]
	if kind != NoticeRecorded && kind != NoticeProcessing {
		return Notice{}, errors.New("unknown notice type " + domain.PyRepr(kind))
	}
	ev, err1 := uuid.Parse(fields["event_id"])
	st, err2 := uuid.Parse(fields["stream_id"])
	if err := errors.Join(err1, err2); err != nil {
		return Notice{}, err
	}
	return Notice{Kind: kind, EventID: ev.String(), StreamID: st.String()}, nil
}

// dispatch hands the notice to every page of the workspace; a page that is too far behind ends.
func (h *noticeHub) dispatch(ws string, n Notice) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for q := range h.queues[ws] {
		select {
		case q <- n:
		default:
			h.log.Warn("An events page is too many notices behind; its stream ends", "workspace_id", ws, "limit", LiveQueueLimit)
			delete(h.queues[ws], q)
			close(q)
		}
	}
}

// LiveFeed is stream_workspace_events: frames for the notices on the streams the caller reads
// whose event passes the filter; result is not applied, an event's result changes as it is
// handled. The channel closes when ctx ends or the page falls too far behind.
func (s *Service) LiveFeed(ctx context.Context, f domain.FeedFilter) (<-chan LiveFrame, error) {
	if s.hub == nil {
		return nil, ErrLiveUnavailable
	}
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	var streams []string
	if err := s.read(ctx, c.Workspace, func(sess db.Session) error {
		streams, err = s.readableStreams(ctx, sess, c)
		return err
	}); err != nil {
		return nil, err
	}
	visible := map[string]bool{}
	for _, id := range streams {
		visible[id] = true
	}
	f.Result = nil
	q, leave, err := s.hub.subscribe(ctx, c.Workspace.ID())
	if err != nil {
		return nil, err
	}
	out := make(chan LiveFrame)
	go func() {
		defer close(out)
		defer leave()
		for {
			var n Notice
			var ok bool
			select {
			case <-ctx.Done():
				return
			case n, ok = <-q:
				if !ok {
					return
				}
			}
			if !visible[n.StreamID] {
				continue
			}
			item, err := s.feedItem(ctx, c.Workspace, f, streams, n.EventID)
			if err != nil {
				if ctx.Err() == nil {
					s.log.Error("Failed to read an event for the live feed", "event_id", n.EventID, "error", err.Error())
				}
				return
			}
			if item == nil {
				continue
			}
			select {
			case out <- LiveFrame{Kind: n.Kind, Item: *item}:
			case <-ctx.Done():
				return
			}
		}
	}()
	return out, nil
}
